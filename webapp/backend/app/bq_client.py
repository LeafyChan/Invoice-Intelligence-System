"""
bq_client.py
============
Singleton BigQuery client + helpers used by the live application.

Two things this file does:
  1. stream_invoice_line_items() — called by drive_sync.py immediately
     after invoice_store.save_invoice_row() commits, so BigQuery stays
     current with every Drive sync rather than needing a manual export.
  2. query_analytics() — thin wrapper used by the /analytics/* routes
     in main.py to run the ITC trend and vendor reliability queries.

BigQuery Sandbox notes:
  - Streaming inserts (client.insert_rows_json) are BLOCKED in sandbox
    mode. We use load_table_from_file (batch load job) instead — this is
    the documented sandbox-compatible path, not a workaround.
  - To keep latency acceptable we buffer rows in memory and flush in one
    load job per sync call, not one job per row.
  - On any BQ error we log and continue — BQ failure must never block the
    primary Postgres write path.

Env vars (already in .env):
  GOOGLE_APPLICATION_CREDENTIALS — path to service account JSON
  BQ_PROJECT_ID                  — GCP project id, e.g. "apac-01072016"
  BQ_DATASET                     — dataset name, default "invoice_intel"
"""

import io
import json
import logging
import os

logger = logging.getLogger(__name__)

_BQ_PROJECT = os.environ.get("BQ_PROJECT_ID", "")
_BQ_DATASET = os.environ.get("BQ_DATASET", "invoice_intel")
_TABLE_ID = "line_items_flat"

# Schema matches bigquery_sync.py exactly so the table definition is compatible
# whether rows came from the manual script or from the live app.
_BQ_SCHEMA = [
    ("line_item_id",          "STRING"),
    ("invoice_id",            "STRING"),
    ("org_id",                "STRING"),   # added vs old script — needed for multi-org analytics
    ("hsn_code",              "STRING"),
    ("amount",                "FLOAT"),
    ("business_use_percent",  "FLOAT"),
    ("line_tax_rate_percent", "FLOAT"),
    ("vendor_name",           "STRING"),
    ("vendor_gstin",          "STRING"),
    ("taxable_amount",        "FLOAT"),
    ("total_gst_amount",      "FLOAT"),
    ("invoice_date",          "DATE"),
    ("status",                "STRING"),
    ("hsn_status",            "STRING"),
]


def _get_client():
    """Lazy import — if google-cloud-bigquery isn't installed the app still
    starts; BQ features just silently no-op (see is_configured())."""
    try:
        from google.cloud import bigquery
        if not _BQ_PROJECT:
            return None
        return bigquery.Client(project=_BQ_PROJECT)
    except ImportError:
        return None


def is_configured() -> bool:
    return bool(_BQ_PROJECT and os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))


def _ensure_table(client) -> object:
    """Creates dataset + table if missing. Returns the table reference."""
    from google.cloud import bigquery

    dataset_ref = bigquery.DatasetReference(_BQ_PROJECT, _BQ_DATASET)
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        ds = bigquery.Dataset(dataset_ref)
        ds.location = "US"
        client.create_dataset(ds)
        logger.info("BQ: created dataset %s", _BQ_DATASET)

    table_ref = dataset_ref.table(_TABLE_ID)
    try:
        client.get_table(table_ref)
    except Exception:
        schema = [bigquery.SchemaField(name, ftype) for name, ftype in _BQ_SCHEMA]
        table = bigquery.Table(table_ref, schema=schema)
        client.create_table(table)
        logger.info("BQ: created table %s", _TABLE_ID)

    return table_ref


def stream_line_items(rows: list[dict]) -> None:
    """
    Batch-loads a list of line-item dicts into BigQuery.
    Called from drive_sync.py after each invoice is committed to Postgres.
    Rows must contain the keys in _BQ_SCHEMA above.
    Errors are logged but never raised — BQ is an analytics mirror, not
    the source of truth, and must not break the primary write path.
    """
    if not rows or not is_configured():
        return
    try:
        from google.cloud import bigquery

        client = _get_client()
        if client is None:
            return

        table_ref = _ensure_table(client)

        # Sandbox-safe batch load via in-memory NDJSON
        buf = io.StringIO()
        field_names = {name for name, _ in _BQ_SCHEMA}
        for row in rows:
            clean = {}
            for k, v in row.items():
                if k not in field_names:
                    continue
                # Bug 20 fix: UUID objects must be str before BQ accepts them.
                # Bug 21 fix: org_id is included in _BQ_SCHEMA and must be str.
                # isoformat() handles date/datetime; str() handles UUID and other types.
                if v is None:
                    clean[k] = None
                elif hasattr(v, "isoformat"):
                    clean[k] = v.isoformat()
                else:
                    clean[k] = str(v)
            buf.write(json.dumps(clean, default=str) + "\n")
        buf.seek(0)

        job_config = bigquery.LoadJobConfig(
            schema=[bigquery.SchemaField(n, t) for n, t in _BQ_SCHEMA],
            write_disposition="WRITE_APPEND",  # append per-sync, not full truncate
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        )
        job = client.load_table_from_file(buf, table_ref, job_config=job_config)
        job.result()  # blocks ~1-3s for small batches — acceptable for sync flow
        logger.info("BQ: appended %d line item rows", len(rows))

    except Exception as exc:
        logger.warning("BQ stream failed (non-fatal): %s", exc)


def query_itc_trend(org_id: str) -> list[dict]:
    """
    Monthly ITC trend for this org — the query that justifies BigQuery's
    existence in the stack (columnar scan across all invoice dates vs
    Postgres's sequential scan). Returns rows sorted by month ascending.
    """
    if not is_configured():
        return []
    try:
        client = _get_client()
        if client is None:
            return []

        sql = f"""
        WITH computed AS (
          SELECT
            FORMAT_DATE('%Y-%m', invoice_date) AS month,
            vendor_name,
            COALESCE(business_use_percent, 100) / 100.0 AS biz_pct,
            CASE
              WHEN line_tax_rate_percent IS NOT NULL
                THEN amount * line_tax_rate_percent / 100.0
              WHEN taxable_amount > 0
                THEN total_gst_amount * (amount / taxable_amount)
              ELSE 0
            END AS line_tax
          FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{_TABLE_ID}`
          WHERE invoice_date IS NOT NULL
            AND org_id = @org_id
        )
        SELECT
          month,
          ROUND(SUM(line_tax * biz_pct), 2)    AS claimable_itc,
          ROUND(SUM(line_tax), 2)               AS gross_itc,
          COUNT(DISTINCT vendor_name)           AS unique_vendors,
          COUNT(*)                              AS line_items
        FROM computed
        GROUP BY month
        ORDER BY month ASC
        """
        from google.cloud import bigquery
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("org_id", "STRING", org_id)]
        )
        results = client.query(sql, job_config=job_config).result()
        return [dict(row) for row in results]
    except Exception as exc:
        logger.warning("BQ itc_trend query failed: %s", exc)
        return []


def query_vendor_reliability(org_id: str) -> list[dict]:
    """
    Vendor reliability score — cross-invoice aggregate showing flag rate
    per vendor. Only possible cheaply in BigQuery at scale.
    """
    if not is_configured():
        return []
    try:
        client = _get_client()
        if client is None:
            return []

        sql = f"""
        SELECT
          COALESCE(vendor_name, '(unknown)')                           AS vendor,
          vendor_gstin,
          COUNT(DISTINCT invoice_id)                                   AS total_invoices,
          COUNTIF(status IN ('FAILED', 'WARNING'))                     AS flagged_invoices,
          ROUND(
            100.0 * COUNTIF(status IN ('FAILED', 'WARNING'))
            / NULLIF(COUNT(DISTINCT invoice_id), 0), 1)               AS flag_rate_pct,
          ROUND(SUM(
            CASE
              WHEN line_tax_rate_percent IS NOT NULL
                THEN amount * line_tax_rate_percent / 100.0
              WHEN taxable_amount > 0
                THEN total_gst_amount * (amount / taxable_amount)
              ELSE 0
            END * COALESCE(business_use_percent, 100) / 100.0
          ), 2)                                                        AS total_claimable_itc
        FROM `{_BQ_PROJECT}.{_BQ_DATASET}.{_TABLE_ID}`
        WHERE org_id = @org_id
        GROUP BY vendor_name, vendor_gstin
        HAVING total_invoices >= 1
        ORDER BY flag_rate_pct DESC, total_invoices DESC
        """
        from google.cloud import bigquery
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("org_id", "STRING", org_id)]
        )
        results = client.query(sql, job_config=job_config).result()
        return [dict(row) for row in results]
    except Exception as exc:
        logger.warning("BQ vendor_reliability query failed: %s", exc)
        return []