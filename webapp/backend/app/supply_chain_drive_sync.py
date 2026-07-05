"""
supply_chain_drive_sync.py — S17
Calls the actual extractor entry points: extract_waybill / extract_grn / extract_material_return
Each takes (file_path, org_id) and returns a dict.
"""
from __future__ import annotations
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _run_sync(
    db, org_id, folder_id, extractor_module, extract_fn_name,
    drive_connector_module, download_dir, already_processed, save_fn,
    result_key, number_key,
):
    all_files = drive_connector_module.list_folder_files(folder_id)
    new_files = [f for f in all_files if f["id"] not in already_processed]
    results = []
    for f in new_files:
        local_path = None
        try:
            local_path = drive_connector_module.download_file(f["id"], f["name"], download_dir)
        except Exception as e:
            results.append({"file_name": f["name"], "drive_file_id": f["id"],
                             "status": "FAILED", "issues": f"Download failed: {e}"})
            continue
        try:
            extract_fn = getattr(extractor_module, extract_fn_name)
            data = extract_fn(local_path, org_id)
        except Exception as e:
            results.append({"file_name": f["name"], "drive_file_id": f["id"],
                             "status": "FAILED", "issues": f"Extraction failed: {e}"})
            continue
        finally:
            if local_path:
                Path(local_path).unlink(missing_ok=True)
        try:
            data["file_name"] = f["name"]
            data["drive_file_id"] = f["id"]
            rec_id = save_fn(db, org_id, data, drive_file_id=f["id"], file_name=f["name"])
            results.append({result_key: rec_id, "file_name": f["name"],
                             number_key: data.get(number_key), "status": "OK",
                             "confidence": data.get("confidence")})
        except Exception as e:
            logger.warning("Save failed for %s: %s", f["name"], e)
            results.append({"file_name": f["name"], "drive_file_id": f["id"],
                             "status": "FAILED", "issues": f"Save failed: {e}"})
    return results


def sync_org_waybill_folder(
    db, org_id, folder_id, waybill_extractor_module, drive_connector_module,
    waybill_schema, download_dir, already_processed_drive_ids, save_waybill_fn, **_
):
    return _run_sync(db, org_id, folder_id, waybill_extractor_module, "extract_waybill",
                     drive_connector_module, download_dir, already_processed_drive_ids,
                     save_waybill_fn, "waybill_id", "ewb_number")


def sync_org_grn_folder(
    db, org_id, folder_id, grn_extractor_module, drive_connector_module,
    grn_schema, download_dir, already_processed_drive_ids, save_grn_fn, **_
):
    return _run_sync(db, org_id, folder_id, grn_extractor_module, "extract_grn",
                     drive_connector_module, download_dir, already_processed_drive_ids,
                     save_grn_fn, "grn_id", "grn_number")


def sync_org_material_return_folder(
    db, org_id, folder_id, mr_extractor_module, drive_connector_module,
    mr_schema, download_dir, already_processed_drive_ids, save_mr_fn, **_
):
    return _run_sync(db, org_id, folder_id, mr_extractor_module, "extract_material_return",
                     drive_connector_module, download_dir, already_processed_drive_ids,
                     save_mr_fn, "mrn_id", "mrn_number")
