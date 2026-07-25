"""
drive_sync.py — fixed sync dedup + error logging to activity_log

Key changes vs original:
  1. is_already_processed replaced with is_successfully_extracted — invoices
     with status FAILED or vendor_name=NULL are retried on next sync instead
     of being permanently skipped.
  2. All extraction/pipeline errors are written to activity_log with the
     actual error message (JSON parse error, token limit, etc) so failures
     are visible and accountable in the Activity tab.
  3. supply_chain_drive_sync follows the same pattern via get_processed_drive_ids
     fix in each store module (waybill/grn/material_return).
"""

import logging
from pathlib import Path
from sqlalchemy import text

from app.invoice_store import save_invoice_row, get_line_items_for_bq
from app import bq_client

logger = logging.getLogger(__name__)


def _log_sync_error(db, org_id: str, file_name: str, drive_file_id: str, error: str):
    """Write a sync failure to activity_log so it shows up in the Activity tab."""
    try:
        db.execute(
            text(
                "INSERT INTO activity_log "
                "(org_id, actor_type, action, entity_type, entity_id, summary) "
                "VALUES (CAST(:oid AS uuid), 'ai', 'sync_error', 'invoice', :eid, :summary)"
            ),
            {
                "oid": org_id,
                "eid": drive_file_id,
                "summary": f"[{file_name}] {error}",
            },
        )
        db.commit()
    except Exception as log_exc:
        logger.warning("Failed to write sync error to activity_log: %s", log_exc)


def is_successfully_extracted(db, org_id: str, drive_file_id: str) -> bool:
    """
    Returns True only if this file has a PASSED or WARNING invoice row for this org.
    FAILED rows and rows with null vendor_name (partial extraction) are treated as
    not-yet-successfully-processed and will be retried on the next sync.

    This replaces the old is_already_processed check which returned True for ANY
    existing row regardless of whether extraction actually succeeded — causing
    failed files to be silently skipped forever.
    """
    row = db.execute(
        text("""
            SELECT 1 FROM invoices
            WHERE org_id = CAST(:oid AS uuid)
              AND drive_file_id = :fid
              AND status IN ('PASSED', 'WARNING')
              AND vendor_name IS NOT NULL
            LIMIT 1
        """),
        {"oid": org_id, "fid": drive_file_id},
    ).fetchone()
    return row is not None


def sync_org_drive_folder(db, org_id: str, folder_id: str, core_pipeline_module,
                           drive_connector_module, schema: dict, download_dir: str,
                           modified_after: str = None) -> list[dict]:
    """
    Lists this org's registered Drive folder, skips files that were already
    SUCCESSFULLY extracted (status PASSED or WARNING, vendor_name not null).
    Files with FAILED status or null vendor_name are retried — they previously
    hit an error (AI token limit, malformed JSON, pipeline crash) and must not
    be permanently skipped.

    All errors are written to activity_log with the actual error message so
    they appear in the Activity tab rather than disappearing silently.
    """
    all_files = drive_connector_module.list_folder_files(folder_id, modified_after=modified_after)
    new_files = [f for f in all_files if not is_successfully_extracted(db, org_id, f["id"])]

    results = []
    for f in new_files:
        local_path = None
        try:
            local_path = drive_connector_module.download_file(f["id"], f["name"], download_dir)
        except Exception as e:
            error_msg = f"Download failed: {e}"
            _log_sync_error(db, org_id, f["name"], f["id"], error_msg)
            results.append({
                "file_name": f["name"], "drive_file_id": f["id"],
                "status": "FAILED", "issues": error_msg,
            })
            continue

        try:
            rows = core_pipeline_module.process_single_pdf(
                Path(local_path), schema, drive_file_id=f["id"]
            )
        except Exception as e:
            error_msg = f"Pipeline processing failed: {e}"
            _log_sync_error(db, org_id, f["name"], f["id"], error_msg)
            results.append({
                "file_name": f["name"], "drive_file_id": f["id"],
                "status": "FAILED", "issues": error_msg,
            })
            continue
        finally:
            if local_path:
                Path(local_path).unlink(missing_ok=True)

        for row in rows:
            row["file_name"] = f["name"]

            # Log extraction-level failures (LLM returned FAILED status) to activity_log
            if row.get("status") == "FAILED":
                issues = row.get("issues") or "Extraction returned FAILED with no detail"
                _log_sync_error(db, org_id, f["name"], f["id"], issues)

            invoice_id = save_invoice_row(
                db, org_id, row, source_type="drive", storage_path=None
            )

            if invoice_id is None:
                logger.info("Skipping duplicate (already saved): %s", f["name"])
                results.append({
                    "file_name": f["name"], "page": row.get("page"),
                    "status": "SKIPPED_DUPLICATE", "confidence": row.get("confidence"),
                })
                continue

            results.append({
                "invoice_id": invoice_id, "file_name": f["name"],
                "page": row.get("page"), "status": row.get("status"),
                "confidence": row.get("confidence"),
                "issues": row.get("issues"),
            })

            if bq_client.is_configured():
                try:
                    bq_rows = get_line_items_for_bq(db, org_id, invoice_id)
                    bq_client.stream_line_items(bq_rows)
                except Exception as exc:
                    logger.warning("BQ stream skipped for invoice %s: %s", invoice_id, exc)

    return results