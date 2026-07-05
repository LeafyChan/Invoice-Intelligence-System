"""
po_gstr2b_drive_sync.py
========================
Extends drive_sync.py's pattern (Drive listing -> download -> process ->
save -> delete local temp copy) to the two new folder types:
  - sync_org_po_folder()      — PO PDFs -> purchase_orders/po_line_items
  - sync_org_gstr2b_folder()  — GSTR-2B Excel files -> gstr2b_documents

Kept as a SEPARATE file from drive_sync.py rather than editing it in place,
since drive_sync.py's existing sync_org_drive_folder() is working,
production code with its own careful comments about why files are deleted
locally and why Storage upload is skipped — those decisions apply
identically here, but mixing three sync functions with three different
row shapes into one file would make a future invoice-only fix riskier to
review. main.py imports both files side by side.

Like drive_sync.py, dedup is org-scoped and uses the *_store modules'
is_already_processed-equivalent checks (passed in by the caller via
already_processed_ids, since purchase_orders/gstr2b_documents don't have
their own app/*_store.py module yet — see note in po_store stub below).
"""

import sys
from pathlib import Path

import openpyxl  # noqa: F401 — re-exported so callers don't need a second import for type checks


def sync_org_po_folder(db, org_id: str, folder_id: str, po_extractor_module,
                        drive_connector_module, po_schema: dict, download_dir: str,
                        already_processed_drive_ids: set, save_po_row_fn,
                        modified_after: str = None) -> list[dict]:
    """
    Mirrors drive_sync.sync_org_drive_folder()'s structure exactly, but for
    PO PDFs: list -> download -> OCR/extract (via po_extractor, NOT
    extractor — different prompt, see po_extractor.py) -> save -> delete
    local temp copy.

    already_processed_drive_ids: set of drive_file_id strings already in
    purchase_orders for this org (caller fetches this once before looping,
    same dedup-key approach as invoices.drive_file_id).
    save_po_row_fn: callable(db, org_id, row, source_type, storage_path) ->
    po_id — passed in rather than imported directly, since app/po_store.py
    does not exist yet (see TODO at bottom of this file). Once it does,
    main.py can pass app.po_store.save_po_row directly with no change here.
    """
    # Reuses core_pipeline's OCR tier (ocr_engine.read_pdf) the SAME way
    # invoices do — POs and invoices are both ordinary PDFs, no PO-specific
    # OCR logic is needed, only the extraction PROMPT differs.
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
    """
    GSTR-2B files are spreadsheets, not OCR targets — no ocr_engine/
    extractor involvement at all, just download -> gstr2b_parser.parse_gstr2b_file
    -> save rows.

    return_period_resolver: callable(file_name: str) -> str ('MM-YYYY').
    GSTR-2B's return period isn't reliably inferable from in-file content
    across portal versions (see gstr2b_parser.py docstring) — the org is
    expected to name files predictably (e.g. "GSTR2B_062026.xlsx") and this
    resolver encodes that convention. Passed in rather than hardcoded here
    so the convention can be changed without editing this file.
    save_gstr2b_rows_fn: callable(db, org_id, rows: list[dict], drive_file_id,
    return_period) -> int (rows inserted) — same "not imported directly"
    rationale as save_po_row_fn above (app/gstr2b_store.py doesn't exist yet).
    """
    sys.path.insert(0, str(Path(__file__).parent))
    import gstr2b_parser as _gp  # noqa: F401 — ensures caller's gstr2b_parser_module is the same module

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


# TODO (next session): app/po_store.py and app/gstr2b_store.py don't exist
# yet — this file's save_po_row_fn / save_gstr2b_rows_fn / already_processed
# params are written as injected callables specifically so main.py can wire
# them up once those store modules exist, without this file changing. See
# the route stubs in main_po_gstr2b_routes.py for the exact call shape
# main.py is expected to use.