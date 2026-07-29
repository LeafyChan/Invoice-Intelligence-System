import sys
from pathlib import Path

import openpyxl  # noqa: F401 — re-exported so callers don't need a second import for type checks


def sync_org_po_folder(db, org_id: str, folder_id: str, po_extractor_module,
                        drive_connector_module, po_schema: dict, download_dir: str,
                        already_processed_drive_ids: set, save_po_row_fn,
                        modified_after: str = None) -> list[dict]:
    sys.path.insert(0, str(Path(download_dir).parent))
    import ocr_engine

    all_files = drive_connector_module.list_folder_files(folder_id, modified_after=modified_after)
    new_files = [f for f in all_files if f["id"] not in already_processed_drive_ids]

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
            pages = ocr_engine.read_pdf(local_path)
        except Exception as e:
            results.append({"file_name": f["name"], "drive_file_id": f["id"],
                             "status": "FAILED", "issues": f"Could not open/read file: {e}"})
            Path(local_path).unlink(missing_ok=True)
            continue

        for page in pages:
            if page.method_used == "needs_vision_ai":
                extracted = po_extractor_module.extract_from_image(page.image, po_schema)
            else:
                extracted = po_extractor_module.extract_from_text(page.raw_text, po_schema)

            row = {"file_name": f["name"], "drive_file_id": f["id"], "page": page.page_number,
                   "extraction_method": page.method_used, "confidence": page.confidence}
            for k, v in extracted.items():
                if k == "_extraction_note":
                    continue
                row[k] = v

            po_id = save_po_row_fn(db, org_id, row, source_type="drive", storage_path=None)
            results.append({"po_id": po_id, "file_name": f["name"], "page": page.page_number,
                             "confidence": page.confidence})

        Path(local_path).unlink(missing_ok=True)

    return results


def sync_org_gstr2b_folder(db, org_id: str, folder_id: str, gstr2b_parser_module,
                            drive_connector_module, download_dir: str,
                            already_processed_drive_ids: set, save_gstr2b_rows_fn,
                            return_period_resolver, modified_after: str = None) -> list[dict]:
    sys.path.insert(0, str(Path(__file__).parent))
    import gstr2b_parser as _gp  

    all_files = drive_connector_module.list_folder_files(folder_id, modified_after=modified_after)
    new_files = [f for f in all_files if f["id"] not in already_processed_drive_ids]

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
            return_period = return_period_resolver(f["name"])
        except Exception as e:
            results.append({"file_name": f["name"], "drive_file_id": f["id"],
                             "status": "FAILED",
                             "issues": f"Could not determine return period from file name: {e}"})
            Path(local_path).unlink(missing_ok=True)
            continue

        try:
            rows = gstr2b_parser_module.parse_gstr2b_file(local_path, return_period)
        except Exception as e:
            results.append({"file_name": f["name"], "drive_file_id": f["id"],
                             "status": "FAILED", "issues": f"Parsing failed: {e}"})
            Path(local_path).unlink(missing_ok=True)
            continue

        for row in rows:
            row["drive_file_id"] = f["id"]
        inserted = save_gstr2b_rows_fn(db, org_id, rows, drive_file_id=f["id"], return_period=return_period)
        results.append({"file_name": f["name"], "drive_file_id": f["id"],
                         "return_period": return_period, "entries_inserted": inserted})

        Path(local_path).unlink(missing_ok=True)

    return results