from __future__ import annotations
import logging
from pathlib import Path
from sqlalchemy import text

logger = logging.getLogger(__name__)


def _log_sync_error(db, org_id: str, file_name: str, drive_file_id: str,
                    entity_type: str, error: str):
    try:
        db.execute(
            text(
                "INSERT INTO activity_log "
                "(org_id, actor_type, action, entity_type, entity_id, summary) "
                "VALUES (CAST(:oid AS uuid), 'ai', 'sync_error', :etype, :eid, :summary)"
            ),
            {
                "oid": org_id, "etype": entity_type,
                "eid": drive_file_id,
                "summary": f"[{file_name}] {error}",
            },
        )
        db.commit()
    except Exception as log_exc:
        logger.warning("Failed to write sync error to activity_log: %s", log_exc)


def _run_sync(
    db, org_id, folder_id, extractor_module, extract_fn_name,
    drive_connector_module, download_dir, already_processed, save_fn,
    result_key, number_key, entity_type,
):
    all_files = drive_connector_module.list_folder_files(folder_id)
    new_files = [f for f in all_files if f["id"] not in already_processed]
    results = []

    for f in new_files:
        local_path = None
        try:
            local_path = drive_connector_module.download_file(f["id"], f["name"], download_dir)
        except Exception as e:
            error_msg = f"Download failed: {e}"
            _log_sync_error(db, org_id, f["name"], f["id"], entity_type, error_msg)
            results.append({"file_name": f["name"], "drive_file_id": f["id"],
                             "status": "FAILED", "issues": error_msg})
            continue

        try:
            extract_fn = getattr(extractor_module, extract_fn_name)
            data = extract_fn(local_path, org_id)
        except Exception as e:
            error_msg = f"Extraction failed: {e}"
            _log_sync_error(db, org_id, f["name"], f["id"], entity_type, error_msg)
            results.append({"file_name": f["name"], "drive_file_id": f["id"],
                             "status": "FAILED", "issues": error_msg})
            continue
        finally:
            if local_path:
                Path(local_path).unlink(missing_ok=True)
        if data.get("status") == "FAILED" or not data.get(number_key):
            issues = data.get("issues") or f"Extraction returned no {number_key} — LLM may have failed"
            _log_sync_error(db, org_id, f["name"], f["id"], entity_type, issues)

        try:
            data["file_name"] = f["name"]
            data["drive_file_id"] = f["id"]
            rec_id = save_fn(db, org_id, data, drive_file_id=f["id"], file_name=f["name"])
            results.append({
                result_key: rec_id, "file_name": f["name"],
                number_key: data.get(number_key), "status": "OK",
                "confidence": data.get("confidence"),
            })
        except Exception as e:
            error_msg = f"Save failed: {e}"
            logger.warning("Save failed for %s: %s", f["name"], e)
            _log_sync_error(db, org_id, f["name"], f["id"], entity_type, error_msg)
            results.append({"file_name": f["name"], "drive_file_id": f["id"],
                             "status": "FAILED", "issues": error_msg})

    return results


def sync_org_waybill_folder(
    db, org_id, folder_id, waybill_extractor_module, drive_connector_module,
    waybill_schema, download_dir, already_processed_drive_ids, save_waybill_fn, **_
):
    return _run_sync(
        db, org_id, folder_id, waybill_extractor_module, "extract_waybill",
        drive_connector_module, download_dir, already_processed_drive_ids,
        save_waybill_fn, "waybill_id", "ewb_number", "waybill",
    )


def sync_org_grn_folder(
    db, org_id, folder_id, grn_extractor_module, drive_connector_module,
    grn_schema, download_dir, already_processed_drive_ids, save_grn_fn, **_
):
    return _run_sync(
        db, org_id, folder_id, grn_extractor_module, "extract_grn",
        drive_connector_module, download_dir, already_processed_drive_ids,
        save_grn_fn, "grn_id", "grn_number", "grn",
    )


def sync_org_material_return_folder(
    db, org_id, folder_id, mr_extractor_module, drive_connector_module,
    mr_schema, download_dir, already_processed_drive_ids, save_mr_fn, **_
):
    return _run_sync(
        db, org_id, folder_id, mr_extractor_module, "extract_material_return",
        drive_connector_module, download_dir, already_processed_drive_ids,
        save_mr_fn, "mrn_id", "mrn_number", "material_return",
    )