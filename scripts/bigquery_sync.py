import argparse
import os
import sys


DATASET_ID = os.environ.get("BQ_DATASET", "invoice_intel")
PROJECT_ID = os.environ.get("BQ_PROJECT_ID", "")

LINE_ITEMS_QUERY = """
SELECT
    li.line_item_id, li.invoice_id, li.hsn_code, li.amount,
    li.business_use_percent, li.line_tax_rate_percent,
    i.vendor_name, i.vendor_gstin, i.taxable_amount, i.total_gst_amount,
    i.invoice_date, i.status,
    hp.confidence AS hsn_status
FROM line_items li
JOIN invoices i ON i.invoice_id = li.invoice_id
LEFT JOIN hsn_profile_codes hp
    ON hp.org_id = li.org_id AND hp.code = li.hsn_code
WHERE li.org_id = :org_id AND i.status != 'FAILED'
"""


def _fetch_rows(db_url: str, org_id: str):
    from sqlalchemy import create_engine, text

    engine = create_engine(db_url)
    with engine.connect() as conn:
        conn.execute(text("SELECT set_config('app.current_org_id', :oid, false)"), {"oid": org_id})
        rows = conn.execute(text(LINE_ITEMS_QUERY), {"org_id": org_id}).mappings().all()
        conn.execute(text("RESET app.current_org_id"))
    return [dict(r) for r in rows]


def sync_to_bigquery(rows: list[dict]):
    from google.cloud import bigquery

    if not PROJECT_ID:
        raise RuntimeError("BQ_PROJECT_ID env var is not set.")

    client = bigquery.Client(project=PROJECT_ID)

    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = "US"
        client.create_dataset(dataset)
        print(f"Created dataset {DATASET_ID}")

    table_ref = dataset_ref.table("line_items_flat")
    schema = [
        bigquery.SchemaField("line_item_id", "STRING"),
        bigquery.SchemaField("invoice_id", "STRING"),
        bigquery.SchemaField("hsn_code", "STRING"),
        bigquery.SchemaField("amount", "FLOAT"),
        bigquery.SchemaField("business_use_percent", "FLOAT"),
        bigquery.SchemaField("line_tax_rate_percent", "FLOAT"),
        bigquery.SchemaField("vendor_name", "STRING"),
        bigquery.SchemaField("vendor_gstin", "STRING"),
        bigquery.SchemaField("taxable_amount", "FLOAT"),
        bigquery.SchemaField("total_gst_amount", "FLOAT"),
        bigquery.SchemaField("invoice_date", "DATE"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("hsn_status", "STRING"),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition="WRITE_TRUNCATE",  
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    import json

    buf = io.StringIO()
    for row in rows:
        clean = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}
        buf.write(json.dumps(clean, default=str) + "\n")
    buf.seek(0)

    load_job = client.load_table_from_file(buf, table_ref, job_config=job_config)
    load_job.result()  

    print(f"Loaded {len(rows):,} rows into {PROJECT_ID}.{DATASET_ID}.line_items_flat")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-url", required=True, help="Supabase Session Pooler connection string")
    parser.add_argument("--org-id", required=True, help="Org UUID to export (RLS-scoped, same as any other read)")
    args = parser.parse_args()

    rows = _fetch_rows(args.db_url, args.org_id)
    if not rows:
        print("No rows found for this org — nothing to sync.")
        sys.exit(0)
    sync_to_bigquery(rows)