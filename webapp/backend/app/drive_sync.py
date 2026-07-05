"""
drive_sync.py
=============
Bridges core/drive_connector.py (Drive listing + downloading) into the
multi-tenant Postgres backend. Dedup is org-scoped via
invoice_store.is_already_processed instead of drive_connector's own
SQLite check.

Files are NOT uploaded to Supabase Storage — they stay in Google Drive.
The drive_file_id is stored on the invoice row and used directly to build
the embeddable /preview URL in the Review Modal.

BIGQUERY INTEGRATION (new):
  After every successful Postgres commit, this module streams the invoice's
  line items to BigQuery via bq_client.stream_line_items(). This replaces
  the old manual bigquery_sync.py script: BigQuery now stays current with
  every Drive sync automatically, with no cron job needed.

  bq_client failures are caught and logged but never re-raised — BigQuery
  is a read-only analytics mirror. Its failure must never block or roll back
  the primary Postgres write.
"""

import logging
from pathlib import Path

from app.invoice_store import is_already_processed, save_invoice_row, get_line_items_for_bq
from app import bq_client

logger = logging.getLogger(__name__)


def sync_org_drive_folder(db, org_id: str, folder_id: str, core_pipeline_module,
                           drive_connector_module, schema: dict, download_dir: str,
                           modified_after: str = None) -> list[dict]:
    """
    Lists this org's registered Drive folder, skips files already processed
    for THIS org, downloads + OCRs + validates new ones, saves results into
    this org's Postgres rows, then streams line items to BigQuery.

    The PDF viewer uses https://drive.google.com/file/d/{drive_file_id}/preview
    directly — embeddable, no auth prompt, no new tab.

    modified_after: ISO 8601 timestamp from orgs.last_drive_sync_at. When set,
      Drive only returns files modified after that point (server-side filter),
      so each sync cycle only touches genuinely new files rather than
      re-listing the entire folder. The dedup check stays as a safety net.
    """
    all_files = drive_connector_module.list_folder_files(folder_id, modified_after=modified_after)
    new_files = [f for f in all_files if not is_already_processed(db, org_id, f["id"])]

    results = []
    for f in new_files:
        local_path = None
        try:
            local_path = drive_connector_module.download_file(f["id"], f["name"], download_dir)
        except Exception as e:
            results.append({
                "file_name": f["name"],
                "drive_file_id": f["id"],
                "status": "FAILED",
                "issues": f"Download failed: {e}",
            })
            continue

        try:
            rows = core_pipeline_module.process_single_pdf(
                Path(local_path), schema, drive_file_id=f["id"]
            )
        except Exception as e:
            results.append({
                "file_name": f["name"],
                "drive_file_id": f["id"],
                "status": "FAILED",
                "issues": f"Pipeline processing failed: {e}",
            })
            continue
        finally:
            if local_path:
                Path(local_path).unlink(missing_ok=True)

        for row in rows:
            row["file_name"] = f["name"]
            invoice_id = save_invoice_row(
                db, org_id, row, source_type="drive", storage_path=None
            )

            # ON CONFLICT DO NOTHING returns None — file already saved for this org, skip silently.
            if invoice_id is None:
                logger.info("Skipping duplicate (already saved): %s", f["name"])
                results.append({
                    "file_name": f["name"],
                    "page": row.get("page"),
                    "status": "SKIPPED_DUPLICATE",
                    "confidence": row.get("confidence"),
                })
                continue

            results.append({
                "invoice_id": invoice_id,
                "file_name": f["name"],
                "page": row.get("page"),
                "status": row.get("status"),
                "confidence": row.get("confidence"),
            })

            # ── BigQuery: stream this invoice's line items ──────────────────
            # Fires after Postgres commit (save_invoice_row already committed).
            # Non-fatal: any BQ error is logged, never re-raised.
            if bq_client.is_configured():
                try:
                    bq_rows = get_line_items_for_bq(db, org_id, invoice_id)
                    bq_client.stream_line_items(bq_rows)
                except Exception as exc:
                    logger.warning(
                        "BQ stream skipped for invoice %s: %s", invoice_id, exc
                    )

    return results