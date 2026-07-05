"""
main.py — Invoice Intelligence API (S19)
"""

import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import json
from app.auth import get_current_org
from app.db import get_org_scoped_db, SessionLocal, _session_with_org
from app.org_resolver import resolve_org_and_user
from app.invoice_store import save_invoice_row, save_placeholder_invoice
from app import storage
from app import bq_client
from app.itc_engine import compute_itc_summary

_core_parent = os.environ.get("CORE_PIPELINE_PATH")
if not _core_parent:
    raise RuntimeError("CORE_PIPELINE_PATH is not set.")
sys.path.insert(0, _core_parent)
sys.path.insert(0, str(Path(_core_parent) / "core"))
import pipeline as core_pipeline   # noqa: E402
import drive_connector              # noqa: E402
from app import hsn_generator                 # noqa: E402
from app.drive_sync import sync_org_drive_folder  # noqa: E402
from app import po_store, exception_store  # noqa: E402
from app.po_gstr2b_drive_sync import sync_org_po_folder  # noqa: E402
import po_extractor as core_po_extractor   # noqa: E402
# ── S17 supply chain ──────────────────────────────────────────────────────────
from app import waybill_store, grn_store, material_return_store, vendor_score_store  # noqa: E402
from app.supply_chain_drive_sync import (  # noqa: E402
    sync_org_waybill_folder, sync_org_grn_folder, sync_org_material_return_folder)
import waybill_extractor as core_waybill_extractor    # noqa: E402
import grn_extractor as core_grn_extractor            # noqa: E402
import material_return_extractor as core_mr_extractor  # noqa: E402
import supply_chain_reconciliation as sc_reconciliation  # noqa: E402

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", tempfile.gettempdir())) / "invoice_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
SCHEMA_PATH = os.environ.get(
    "INVOICE_SCHEMA_PATH", str(Path(_core_parent) / "config" / "invoice_schema.json"))
PO_SCHEMA_PATH = os.environ.get(
    "PO_SCHEMA_PATH", str(Path(_core_parent) / "core" / "config" / "po_schema.json"))
WAYBILL_SCHEMA_PATH = os.environ.get(
    "WAYBILL_SCHEMA_PATH", str(Path(_core_parent) / "core" / "config" / "waybill_schema.json"))
GRN_SCHEMA_PATH = os.environ.get(
    "GRN_SCHEMA_PATH", str(Path(_core_parent) / "core" / "config" / "grn_schema.json"))
MR_SCHEMA_PATH = os.environ.get(
    "MR_SCHEMA_PATH",
    str(Path(_core_parent) / "core" / "config" / "material_return_schema.json"))
DRIVE_POLL_SECRET = os.environ.get("DRIVE_POLL_SECRET")

_SORTABLE_COLUMNS = frozenset({
    "processed_at", "invoice_date", "file_name", "vendor_name",
    "total_amount", "confidence", "status"})
_EDITABLE_INVOICE_FIELDS = frozenset({
    "vendor_name", "vendor_gstin", "buyer_name", "buyer_gstin",
    "invoice_number", "invoice_date", "payment_due_date", "place_of_supply",
    "taxable_amount", "cgst_amount", "sgst_amount", "igst_amount",
    "total_gst_amount", "total_amount", "currency_code", "po_number"})
_VALID_FOLDER_TYPES = frozenset({
    "invoices", "purchase_orders",
    "waybills", "grn", "material_return",
})

app = FastAPI(title="Invoice Intelligence API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)


def get_request_context(clerk_ctx: dict = Depends(get_current_org)) -> dict:
    resolved = resolve_org_and_user(
        clerk_org_id=clerk_ctx["org_id"], clerk_user_id=clerk_ctx["user_id"])
    return {**clerk_ctx, **resolved}


def get_db_for_request(ctx: dict = Depends(get_request_context)):
    with get_org_scoped_db(ctx["org_id"]) as db:
        yield db


def log_activity(db: Session, org_id: str, *, actor_type: str, action: str,
                  entity_type: str, entity_id: str = None, field_name: str = None,
                  old_value=None, new_value=None, summary: str = None,
                  actor_id: str = None):
    db.execute(
        text(
            "INSERT INTO activity_log "
            "(org_id, actor_type, actor_id, action, entity_type, entity_id, "
            " field_name, old_value, new_value, summary) "
            "VALUES (CAST(:oid AS uuid), :atype, CAST(:aid AS uuid), :action, :etype, :eid, "
            " :field, :old, :new, :summary)"
        ),
        {
            "oid": org_id, "atype": actor_type, "aid": actor_id, "action": action,
            "etype": entity_type, "eid": entity_id, "field": field_name,
            "old": str(old_value) if old_value is not None else None,
            "new": str(new_value) if new_value is not None else None,
            "summary": summary,
        },
    )


def _reconcile_invoice_amounts(db: Session, invoice_id: str) -> list[str]:
    try:
        schema = core_pipeline.load_schema(SCHEMA_PATH)
        tolerance = schema["validation_rules"]["amount_reconciliation_tolerance"]
    except Exception:
        tolerance = 1.0
    row = db.execute(
        text("SELECT taxable_amount, total_gst_amount, total_amount "
             "FROM invoices WHERE invoice_id = :iid"),
        {"iid": invoice_id}).mappings().fetchone()
    if not row:
        return []
    line_sum = db.execute(
        text("SELECT COALESCE(SUM(amount), 0) FROM line_items "
             "WHERE invoice_id = :iid AND amount IS NOT NULL"),
        {"iid": invoice_id}).scalar()
    has_line_items = db.execute(
        text("SELECT COUNT(*) FROM line_items "
             "WHERE invoice_id = :iid AND amount IS NOT NULL"),
        {"iid": invoice_id}).scalar()
    taxable, gst, total = (
        row["taxable_amount"], row["total_gst_amount"], row["total_amount"])
    issues = []
    if has_line_items and taxable is not None:
        if abs(float(line_sum) - float(taxable)) > tolerance:
            issues.append(
                f"Line items sum to {line_sum:.2f}, but taxable_amount is {taxable:.2f}")
    if taxable is not None and gst is not None and total is not None:
        expected_total = float(taxable) + float(gst)
        if abs(expected_total - float(total)) > tolerance:
            issues.append(
                f"taxable_amount ({taxable:.2f}) + total_gst_amount ({gst:.2f}) = "
                f"{expected_total:.2f}, but total_amount is {total:.2f}")
    return issues


def _extract_drive_folder_id(raw: str) -> str:
    raw = raw.strip()
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", raw)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_-]{10,}", raw):
        return raw
    raise ValueError(
        "Could not find a Drive folder ID. Paste the folder ID or full folder URL.")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/me")
def whoami(ctx: dict = Depends(get_request_context)):
    return {"org_id": ctx["org_id"], "user_id": ctx["user_id"]}

@app.get("/invoices/_smoke_test")
def invoices_smoke_test(db: Session = Depends(get_db_for_request)):
    return {
        "invoice_count_for_this_org":
            db.execute(text("SELECT COUNT(*) FROM invoices")).scalar()
    }


# ── Upload ────────────────────────────────────────────────────────────────────

@app.post("/invoices/upload")
async def upload_invoice(
    file: UploadFile,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    if not file.filename.lower().endswith((".pdf", ".png", ".jpg", ".jpeg", ".tiff")):
        raise HTTPException(400, "Only PDF and common image formats are accepted")
    safe_name = f"{uuid.uuid4()}_{file.filename}"
    local_path = UPLOAD_DIR / safe_name
    contents = await file.read()
    local_path.write_bytes(contents)
    schema = core_pipeline.load_schema(SCHEMA_PATH)
    try:
        rows = core_pipeline.process_single_pdf(local_path, schema)
    except Exception as e:
        local_path.unlink(missing_ok=True)
        raise HTTPException(500, f"Pipeline processing failed: {e}")
    if storage.is_configured():
        try:
            storage_path = storage.upload_file(
                ctx["org_id"], file.filename, contents,
                content_type=file.content_type or "application/octet-stream")
        except Exception as e:
            local_path.unlink(missing_ok=True)
            raise HTTPException(500, f"Storage upload failed: {e}")
        local_path.unlink(missing_ok=True)
    else:
        storage_path = str(local_path)
    saved = []
    for row in rows:
        row["file_name"] = file.filename
        invoice_id = save_invoice_row(
            db, ctx["org_id"], row, source_type="upload", storage_path=storage_path)
        saved.append({
            "invoice_id": invoice_id, "page": row.get("page"),
            "status": row.get("status"), "confidence": row.get("confidence"),
        })
    return {"file_name": file.filename, "pages_processed": len(saved), "results": saved}


# ── File URL ──────────────────────────────────────────────────────────────────

@app.get("/invoices/{invoice_id}/file-url")
def get_file_url(invoice_id: str, db: Session = Depends(get_db_for_request)):
    row = db.execute(
        text("SELECT storage_path, drive_file_id FROM invoices WHERE invoice_id = :iid"),
        {"iid": invoice_id}).fetchone()
    if not row:
        raise HTTPException(404, "Invoice not found")
    storage_path, drive_file_id = row[0], row[1]
    drive_fallback = {"drive_file_id": drive_file_id} if drive_file_id else {}
    if not storage_path or not storage.is_configured() \
            or not storage_path.startswith("invoices/"):
        return {"url": None, **drive_fallback}
    try:
        return {"url": storage.get_signed_url(storage_path), **drive_fallback}
    except Exception as e:
        return {"url": None, "storage_error": str(e), **drive_fallback}



@app.get("/invoices/{invoice_id}/linked-docs")
def get_linked_docs(invoice_id: str, db: Session = Depends(get_db_for_request)):
    """Returns Drive file IDs for documents linked to this invoice (PO, waybill, GRN, MRN)."""
    inv = db.execute(
        text("SELECT po_number, waybill_number, grn_number, mrn_number FROM invoices WHERE invoice_id = :iid"),
        {"iid": invoice_id}).fetchone()
    if not inv:
        raise HTTPException(404, "Invoice not found")
    po_number, waybill_number, grn_number, mrn_number = inv

    result = {}

    if po_number:
        row = db.execute(
            text("SELECT drive_file_id FROM purchase_orders WHERE po_number = :n LIMIT 1"),
            {"n": po_number}).fetchone()
        if row and row[0]:
            result["purchase_order"] = row[0]

    if waybill_number:
        row = db.execute(
            text("SELECT drive_file_id FROM waybills WHERE ewb_number = :n LIMIT 1"),
            {"n": waybill_number}).fetchone()
        if row and row[0]:
            result["waybill"] = row[0]

    if grn_number:
        row = db.execute(
            text("SELECT drive_file_id FROM grn WHERE grn_number = :n LIMIT 1"),
            {"n": grn_number}).fetchone()
        if row and row[0]:
            result["grn"] = row[0]

    if mrn_number:
        row = db.execute(
            text("SELECT drive_file_id FROM material_returns WHERE mrn_number = :n LIMIT 1"),
            {"n": mrn_number}).fetchone()
        if row and row[0]:
            result["material_return"] = row[0]

    return result


# ── Org settings ──────────────────────────────────────────────────────────────

class _DriveFolderBody(BaseModel):
    folder_id: str

@app.put("/org/drive-folder")
def set_drive_folder(
    body: _DriveFolderBody,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    try:
        folder_id = _extract_drive_folder_id(body.folder_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    prior = db.execute(
        text("SELECT drive_folder_id FROM orgs WHERE org_id = :oid"),
        {"oid": ctx["org_id"]}).fetchone()
    prior_folder_id = prior[0] if prior else None
    try:
        db.execute(
            text("UPDATE orgs SET drive_folder_id = :fid WHERE org_id = :oid"),
            {"fid": folder_id, "oid": ctx["org_id"]})
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This Drive folder is already registered to another account.")
    log_activity(
        db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
        action="settings_update", entity_type="drive_folder", entity_id=folder_id,
        field_name="drive_folder_id", old_value=prior_folder_id, new_value=folder_id,
        summary=f"Drive folder set to {folder_id}")
    return {"org_id": ctx["org_id"], "drive_folder_id": folder_id}

@app.get("/org/drive-folder")
def get_drive_folder(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    row = db.execute(
        text("SELECT drive_folder_id FROM orgs WHERE org_id = :oid"),
        {"oid": ctx["org_id"]}).fetchone()
    return {"org_id": ctx["org_id"], "drive_folder_id": row[0] if row else None}


class _OrgSettingsBody(BaseModel):
    business_description: str

@app.put("/org/settings")
def set_org_settings(
    body: _OrgSettingsBody,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    desc = body.business_description.strip()
    if not desc:
        raise HTTPException(400, "business_description cannot be empty")
    prior = db.execute(
        text("SELECT business_description FROM orgs WHERE org_id = :oid"),
        {"oid": ctx["org_id"]}).fetchone()
    db.execute(
        text("UPDATE orgs SET business_description = :d WHERE org_id = :oid"),
        {"d": desc, "oid": ctx["org_id"]})
    log_activity(
        db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
        action="settings_update", entity_type="business_description",
        field_name="business_description",
        old_value=prior[0] if prior else None, new_value=desc,
        summary="Business description updated")
    return {"org_id": ctx["org_id"], "business_description": desc}

@app.get("/org/settings")
def get_org_settings(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    row = db.execute(
        text("SELECT business_description FROM orgs WHERE org_id = :oid"),
        {"oid": ctx["org_id"]}).fetchone()
    return {"org_id": ctx["org_id"], "business_description": row[0] if row else None}


# ── HSN/SAC profile ───────────────────────────────────────────────────────────

def _load_hsn_profile(db: Session, org_id: str) -> dict:
    rows = db.execute(
        text("SELECT code, code_type, description, confidence, source, added_at "
             "FROM hsn_profile_codes WHERE org_id = :oid ORDER BY code"),
        {"oid": org_id}).mappings().all()
    expected = [dict(r) for r in rows if r["confidence"] != "ambiguous"]
    ambiguous = [dict(r) for r in rows if r["confidence"] == "ambiguous"]
    return {
        "org_id": org_id,
        "expected_hsn_codes": expected,
        "ambiguous_hsn_codes": ambiguous,
        "has_profile": len(rows) > 0,
    }

@app.get("/org/hsn-profile")
def get_hsn_profile(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    return _load_hsn_profile(db, ctx["org_id"])

@app.post("/org/hsn-profile/generate")
def generate_hsn_profile_preview(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    org_row = db.execute(
        text("SELECT business_description FROM orgs WHERE org_id = :oid"),
        {"oid": ctx["org_id"]}).fetchone()
    desc = org_row[0] if org_row else None
    if not desc:
        raise HTTPException(400, "No business description saved yet. Save one in Settings first.")
    try:
        generated = hsn_generator.generate_hsn_profile(desc)
    except Exception as e:
        raise HTTPException(500, f"HSN generation failed: {e}")
    existing_rows = db.execute(
        text("SELECT code, confidence, source FROM hsn_profile_codes WHERE org_id = :oid"),
        {"oid": ctx["org_id"]}).mappings().all()
    existing_codes = {r["code"] for r in existing_rows}
    manual_codes = {r["code"] for r in existing_rows if r["source"] == "manual"}
    gen_expected = generated.get("expected_codes", [])
    gen_ambiguous = generated.get("ambiguous_codes", [])
    gen_codes = {c["code"] for c in gen_expected} | {c["code"] for c in gen_ambiguous}
    new_codes = [c for c in (gen_expected + gen_ambiguous) if c["code"] not in existing_codes]
    return {
        "expected_codes": gen_expected,
        "ambiguous_codes": gen_ambiguous,
        "diff": {
            "new_codes": [c["code"] for c in new_codes],
            "codes_no_longer_suggested": sorted(existing_codes - gen_codes - manual_codes),
            "unchanged_codes": sorted(existing_codes & gen_codes),
        },
    }

class _HsnApplyBody(BaseModel):
    expected_codes: list[dict] = []
    ambiguous_codes: list[dict] = []
    remove_codes: list[str] = []

@app.post("/org/hsn-profile/apply")
def apply_hsn_profile(
    body: _HsnApplyBody,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    for c in body.expected_codes + body.ambiguous_codes:
        confidence = "ambiguous" if c in body.ambiguous_codes else "expected"
        db.execute(
            text(
                "INSERT INTO hsn_profile_codes "
                "(org_id, code, code_type, description, confidence, source) "
                "VALUES (:oid, :code, :ctype, :desc, :conf, 'generated') "
                "ON CONFLICT (org_id, code) DO UPDATE SET "
                "  code_type = EXCLUDED.code_type, description = EXCLUDED.description, "
                "  confidence = EXCLUDED.confidence "
                "WHERE hsn_profile_codes.source = 'generated'"
            ),
            {"oid": ctx["org_id"], "code": c["code"],
             "ctype": c.get("code_type", "HSN"),
             "desc": c.get("description"), "conf": confidence})
    for code in body.remove_codes:
        db.execute(
            text(
                "DELETE FROM hsn_profile_codes WHERE org_id = :oid AND code = :code "
                "AND source = 'generated'"
            ),
            {"oid": ctx["org_id"], "code": code})
    log_activity(
        db, ctx["org_id"], actor_type="ai", actor_id=ctx["user_id"],
        action="hsn_profile_apply", entity_type="hsn_profile",
        summary=(f"Applied HSN profile: {len(body.expected_codes)} expected, "
                 f"{len(body.ambiguous_codes)} ambiguous, {len(body.remove_codes)} removed"))
    return _load_hsn_profile(db, ctx["org_id"])

class _HsnManualCodeBody(BaseModel):
    code: str
    code_type: str = "HSN"
    description: Optional[str] = None

@app.post("/org/hsn-profile/codes")
def add_manual_hsn_code(
    body: _HsnManualCodeBody,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    code = body.code.strip().upper()
    if not code:
        raise HTTPException(400, "code cannot be empty")
    if body.code_type not in ("HSN", "SAC"):
        raise HTTPException(400, "code_type must be 'HSN' or 'SAC'")
    db.execute(
        text(
            "INSERT INTO hsn_profile_codes "
            "(org_id, code, code_type, description, confidence, source) "
            "VALUES (:oid, :code, :ctype, :desc, 'expected', 'manual') "
            "ON CONFLICT (org_id, code) DO UPDATE SET "
            "  code_type = EXCLUDED.code_type, description = EXCLUDED.description"
        ),
        {"oid": ctx["org_id"], "code": code,
         "ctype": body.code_type, "desc": body.description})
    log_activity(
        db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
        action="hsn_code_add", entity_type="hsn_profile_code", entity_id=code,
        new_value=code, summary=f"Manually added HSN/SAC code {code}")
    return _load_hsn_profile(db, ctx["org_id"])

@app.delete("/org/hsn-profile/codes/{code}")
def remove_hsn_code(
    code: str,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    result = db.execute(
        text("DELETE FROM hsn_profile_codes WHERE org_id = :oid AND code = :code"),
        {"oid": ctx["org_id"], "code": code})
    if result.rowcount == 0:
        raise HTTPException(404, f"Code '{code}' not found in profile")
    log_activity(
        db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
        action="hsn_code_remove", entity_type="hsn_profile_code", entity_id=code,
        old_value=code, summary=f"Removed HSN/SAC code {code}")
    return _load_hsn_profile(db, ctx["org_id"])


# ── Drive sync ────────────────────────────────────────────────────────────────

@app.post("/drive/sync")
def sync_drive(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    row = db.execute(
        text("SELECT drive_folder_id FROM orgs WHERE org_id = :oid"),
        {"oid": ctx["org_id"]}).fetchone()
    folder_id = row[0] if row else None
    if not folder_id:
        raise HTTPException(400, "No Drive folder registered. Go to Settings first.")
    schema = core_pipeline.load_schema(SCHEMA_PATH)
    try:
        results = sync_org_drive_folder(
            db, ctx["org_id"], folder_id, core_pipeline,
            drive_connector, schema, str(UPLOAD_DIR))
    except Exception as e:
        raise HTTPException(500, f"Drive sync failed: {e}")
    return {"folder_id": folder_id, "new_files_processed": len(results), "results": results}


# ── S19: Force rescan selected invoices ───────────────────────────────────────

class _RescanBody(BaseModel):
    drive_file_ids: list[str]

@app.post("/invoices/rescan")
def rescan_invoices(
    body: _RescanBody,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    """Force re-extract specific invoice files by drive_file_id.
    Marks existing rows as FAILED + clears vendor_name so the ON CONFLICT
    UPDATE in save_invoice_row will overwrite them on re-extraction."""
    if not body.drive_file_ids:
        raise HTTPException(400, "drive_file_ids cannot be empty")
    # Mark rows as FAILED so they get retried (don't delete — preserves
    # invoice_id references used by line_items, exceptions, etc.)
    for fid in body.drive_file_ids:
        db.execute(
            text(
                "UPDATE invoices SET status = 'FAILED', vendor_name = NULL "
                "WHERE org_id = CAST(:oid AS uuid) AND drive_file_id = :fid"
            ),
            {"oid": ctx["org_id"], "fid": fid})
    db.commit()
    # Get the invoices Drive folder
    folder_row = db.execute(
        text(
            "SELECT folder_id FROM org_drive_folders "
            "WHERE org_id = CAST(:oid AS uuid) AND folder_type = 'invoices'"
        ),
        {"oid": ctx["org_id"]}).fetchone()
    if not folder_row or not folder_row[0]:
        raise HTTPException(400, "No invoices Drive folder registered.")
    schema = core_pipeline.load_schema(SCHEMA_PATH)
    all_files = drive_connector.list_folder_files(folder_row[0])
    target_ids = set(body.drive_file_ids)
    target_files = [f for f in all_files if f["id"] in target_ids]
    results = []
    for f in target_files:
        try:
            local_path = drive_connector.download_file(f["id"], f["name"], str(UPLOAD_DIR))
            rows = core_pipeline.process_single_pdf(
                local_path, schema, drive_file_id=f["id"])
            Path(local_path).unlink(missing_ok=True)
            for row in rows:
                row["file_name"] = f["name"]
                invoice_id = save_invoice_row(
                    db, ctx["org_id"], row, source_type="drive")
                results.append({
                    "file_name": f["name"], "invoice_id": invoice_id,
                    "status": row.get("status"),
                })
        except Exception as e:
            results.append({"file_name": f["name"], "status": "FAILED", "error": str(e)})
    return {"rescanned": len(target_files), "results": results}


# ── Background poll ───────────────────────────────────────────────────────────

@app.post("/admin/drive-poll-all")
def drive_poll_all(x_poll_secret: str = Header(default="")):
    if not DRIVE_POLL_SECRET or x_poll_secret != DRIVE_POLL_SECRET:
        raise HTTPException(401, "Invalid or missing poll secret")
    admin = SessionLocal()
    try:
        orgs = admin.execute(
            text("SELECT org_id, drive_folder_id FROM orgs WHERE drive_folder_id IS NOT NULL")
        ).fetchall()
    finally:
        admin.close()
    schema = core_pipeline.load_schema(SCHEMA_PATH)
    summary = []
    for org_id, folder_id in orgs:
        try:
            with _session_with_org(str(org_id)) as db:
                results = sync_org_drive_folder(
                    db, str(org_id), folder_id, core_pipeline,
                    drive_connector, schema, str(UPLOAD_DIR))
            summary.append({"org_id": str(org_id), "new_files_processed": len(results)})
        except Exception as e:
            summary.append({"org_id": str(org_id), "error": str(e)})
    return {"orgs_polled": len(orgs), "results": summary}


# ── Invoice PATCH ─────────────────────────────────────────────────────────────

class _LineItemPatch(BaseModel):
    line_item_id: Optional[str] = None
    description: Optional[str] = None
    hsn_code: Optional[str] = None
    quantity: Optional[float] = None
    rate: Optional[float] = None
    amount: Optional[float] = None
    line_tax_rate_percent: Optional[float] = None
    business_use_percent: Optional[float] = None
    delete: bool = False

class _InvoicePatch(BaseModel):
    fields: dict = {}
    line_items: list[_LineItemPatch] = []

@app.patch("/invoices/{invoice_id}")
def patch_invoice(
    invoice_id: str, body: _InvoicePatch,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    bad = set(body.fields.keys()) - _EDITABLE_INVOICE_FIELDS
    if bad:
        raise HTTPException(400, f"Non-editable fields: {', '.join(sorted(bad))}")
    current = db.execute(
        text("SELECT * FROM invoices WHERE invoice_id = :iid"),
        {"iid": invoice_id}).mappings().fetchone()
    if not current:
        raise HTTPException(404, "Invoice not found")
    if body.fields:
        set_clause = ", ".join(f"{k} = :{k}" for k in body.fields)
        db.execute(
            text(f"UPDATE invoices SET {set_clause}, is_user_verified = true, "
                 "last_edited_by = CAST(:uid AS uuid), last_edited_at = now() "
                 "WHERE invoice_id = :iid"),
            {**body.fields, "iid": invoice_id, "uid": ctx["user_id"]})
        for field, new_val in body.fields.items():
            old_val = current.get(field)
            if str(old_val or "") != str(new_val or ""):
                db.execute(
                    text(
                        "INSERT INTO edit_history "
                        "(org_id, invoice_id, edited_by, field_name, old_value, new_value, edit_reason) "
                        "VALUES (:oid, :iid, CAST(:uid AS uuid), :field, :old, :new, 'correction')"
                    ),
                    {"oid": ctx["org_id"], "iid": invoice_id, "uid": ctx["user_id"],
                     "field": field,
                     "old": str(old_val) if old_val is not None else None,
                     "new": str(new_val) if new_val is not None else None})
                log_activity(
                    db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
                    action="invoice_field_edit", entity_type="invoice",
                    entity_id=invoice_id, field_name=field,
                    old_value=old_val, new_value=new_val,
                    summary=f"{field} changed on {current.get('file_name') or invoice_id}")
    for li in body.line_items:
        if li.delete and li.line_item_id:
            prior = db.execute(
                text("SELECT description FROM line_items WHERE line_item_id = :lid"),
                {"lid": li.line_item_id}).mappings().fetchone()
            db.execute(
                text("DELETE FROM line_items WHERE line_item_id = :lid"),
                {"lid": li.line_item_id})
            log_activity(
                db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
                action="line_item_delete", entity_type="line_item",
                entity_id=li.line_item_id,
                old_value=prior["description"] if prior else None,
                summary=f"Deleted line item on {current.get('file_name') or invoice_id}")
        elif li.line_item_id:
            db.execute(
                text(
                    "UPDATE line_items SET "
                    "  description = COALESCE(:desc, description), "
                    "  hsn_code = COALESCE(:hsn, hsn_code), "
                    "  quantity = COALESCE(:qty, quantity), "
                    "  rate = COALESCE(:rate, rate), "
                    "  amount = COALESCE(:amt, amount), "
                    "  line_tax_rate_percent = COALESCE(:ltrp, line_tax_rate_percent), "
                    "  business_use_percent = COALESCE(:bup, business_use_percent, 100) "
                    "WHERE line_item_id = :lid"
                ),
                {"lid": li.line_item_id, "desc": li.description, "hsn": li.hsn_code,
                 "qty": li.quantity, "rate": li.rate, "amt": li.amount,
                 "ltrp": li.line_tax_rate_percent, "bup": li.business_use_percent})
        elif not li.delete:
            result = db.execute(
                text(
                    "INSERT INTO line_items "
                    "(org_id, invoice_id, description, hsn_code, quantity, rate, amount, "
                    " line_tax_rate_percent, business_use_percent) "
                    "VALUES (:oid, :iid, :desc, :hsn, :qty, :rate, :amt, :ltrp, :bup) "
                    "RETURNING line_item_id"
                ),
                {"oid": ctx["org_id"], "iid": invoice_id,
                 "desc": li.description, "hsn": li.hsn_code,
                 "qty": li.quantity, "rate": li.rate, "amt": li.amount,
                 "ltrp": li.line_tax_rate_percent,
                 "bup": li.business_use_percent
                      if li.business_use_percent is not None else 100})
            log_activity(
                db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
                action="line_item_add", entity_type="line_item",
                entity_id=str(result.scalar()), new_value=li.description,
                summary=f"Added line item on {current.get('file_name') or invoice_id}")
    reconciliation_issues = _reconcile_invoice_amounts(db, invoice_id)
    if reconciliation_issues:
        db.execute(
            text("UPDATE invoices SET status = 'WARNING', issues = :issues "
                 "WHERE invoice_id = :iid"),
            {"iid": invoice_id, "issues": "; ".join(reconciliation_issues)})
    elif current.get("status") == "WARNING" and current.get("issues") and (
        "taxable_amount is" in current["issues"]
        or "total_amount is" in current["issues"]
    ):
        db.execute(
            text("UPDATE invoices SET status = 'PASSED', issues = NULL "
                 "WHERE invoice_id = :iid"),
            {"iid": invoice_id})
    return {
        "invoice_id": invoice_id, "updated": True,
        "reconciliation_issues": reconciliation_issues,
    }


# ── Activity log ──────────────────────────────────────────────────────────────

@app.get("/activity-log")
def get_activity_log(
    db: Session = Depends(get_db_for_request),
    entity_type: Optional[str] = Query(default=None),
    actor_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    filters, params = [], {}
    if entity_type:
        filters.append("entity_type = :etype"); params["etype"] = entity_type
    if actor_type:
        if actor_type not in ("user", "ai"):
            raise HTTPException(400, "actor_type must be 'user' or 'ai'")
        filters.append("actor_type = :atype"); params["atype"] = actor_type
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size
    count_p = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    total = db.execute(
        text(f"SELECT COUNT(*) FROM activity_log {where}"), count_p).scalar()
    rows = db.execute(
        text(f"SELECT log_id, actor_type, actor_id, action, entity_type, entity_id, "
             f"field_name, old_value, new_value, summary, created_at "
             f"FROM activity_log {where} ORDER BY created_at DESC "
             f"LIMIT :limit OFFSET :offset"),
        params).mappings().all()
    return {
        "total_count": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
        "entries": [dict(r) for r in rows],
    }


# ── Invoice list ──────────────────────────────────────────────────────────────

@app.get("/invoices")
def list_invoices(
    db: Session = Depends(get_db_for_request),
    status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    po_number: Optional[str] = Query(default=None),
    vendor_gstin: Optional[str] = Query(default=None),
    paid: Optional[bool] = Query(default=None),
    sort_by: str = Query(default="processed_at"),
    sort_dir: str = Query(default="desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    col = sort_by if sort_by in _SORTABLE_COLUMNS else "processed_at"
    direction = "DESC" if sort_dir.strip().upper() == "DESC" else "ASC"
    filters, params = ["1=1"], {}
    if status:
        if status not in {
            "PASSED", "WARNING", "FAILED", "NEEDS_MANUAL_REVIEW", "PLACEHOLDER"
        }:
            raise HTTPException(400, f"Invalid status '{status}'")
        filters.append("i.status = :status"); params["status"] = status
    if search:
        filters.append(
            "(i.vendor_name ILIKE :search OR i.invoice_number ILIKE :search "
            " OR i.po_number ILIKE :search)")
        params["search"] = f"%{search}%"
    if po_number:
        filters.append("i.po_number ILIKE :po_number")
        params["po_number"] = f"%{po_number}%"
    if vendor_gstin:
        filters.append("i.vendor_gstin ILIKE :vgstin")
        params["vgstin"] = f"%{vendor_gstin}%"
    if paid is not None:
        filters.append("i.is_paid = :paid"); params["paid"] = paid
    where = "WHERE " + " AND ".join(filters)
    params["limit"] = page_size
    params["offset"] = (page - 1) * page_size
    count_p = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    total = db.execute(
        text(f"SELECT COUNT(*) FROM invoices i {where}"), count_p).scalar()
    rows = db.execute(
        text(f"""
            SELECT
                i.invoice_id, i.file_name, i.page, i.vendor_name, i.vendor_gstin,
                i.invoice_number, i.invoice_date, i.po_number,
                i.total_amount, i.total_gst_amount, i.taxable_amount,
                i.payment_terms, i.advance_paid_amount,
                i.status, i.confidence, i.extraction_method,
                i.issues, i.is_user_verified, i.processed_at,
                i.is_paid, i.paid_at, i.drive_file_id,
                CASE WHEN i.taxable_amount > 0
                     THEN ROUND(i.total_gst_amount / i.taxable_amount * 100, 2)
                     ELSE NULL END AS tax_rate_pct,
                -- PO fields
                po.po_date,
                po.delivery_date_requested,
                po.payment_terms AS po_payment_terms,
                po.incoterm AS po_incoterm,
                po.incoterm_raw AS po_incoterm_raw,
                po.incoterm_named_place AS po_incoterm_named_place,
                -- Waybill (first linked via invoice_number → document_number)
                (SELECT w.ewb_number FROM waybills w
                 WHERE w.document_number = i.invoice_number
                   AND w.org_id = i.org_id LIMIT 1) AS waybill_number,
                -- GRN (first linked via waybill or PO)
                (SELECT g.grn_number FROM grn g
                 WHERE (g.po_number = i.po_number
                    OR g.waybill_number = (
                        SELECT w2.ewb_number FROM waybills w2
                        WHERE w2.document_number = i.invoice_number
                          AND w2.org_id = i.org_id LIMIT 1))
                   AND g.org_id = i.org_id LIMIT 1) AS grn_number,
                (SELECT g.grn_date FROM grn g
                 WHERE (g.po_number = i.po_number
                    OR g.waybill_number = (
                        SELECT w2.ewb_number FROM waybills w2
                        WHERE w2.document_number = i.invoice_number
                          AND w2.org_id = i.org_id LIMIT 1))
                   AND g.org_id = i.org_id LIMIT 1) AS grn_date,
                -- MRN
                (SELECT mr.mrn_number FROM material_returns mr
                 WHERE (mr.grn_number = (
                     SELECT g3.grn_number FROM grn g3
                     WHERE (g3.po_number = i.po_number
                        OR g3.waybill_number = (
                            SELECT w3.ewb_number FROM waybills w3
                            WHERE w3.document_number = i.invoice_number
                              AND w3.org_id = i.org_id LIMIT 1))
                       AND g3.org_id = i.org_id LIMIT 1)
                  OR mr.po_number = i.po_number)
                   AND mr.org_id = i.org_id LIMIT 1) AS mrn_number,
                -- Drive file IDs for PWGM doc-chain indicators
                po.drive_file_id AS po_drive_file_id,
                (SELECT w.drive_file_id FROM waybills w
                 WHERE w.document_number = i.invoice_number
                   AND w.org_id = i.org_id LIMIT 1) AS waybill_drive_file_id,
                (SELECT g.drive_file_id FROM grn g
                 WHERE (g.po_number = i.po_number
                    OR g.waybill_number = (
                        SELECT w2.ewb_number FROM waybills w2
                        WHERE w2.document_number = i.invoice_number
                          AND w2.org_id = i.org_id LIMIT 1))
                   AND g.org_id = i.org_id LIMIT 1) AS grn_drive_file_id,
                (SELECT mr.drive_file_id FROM material_returns mr
                 WHERE (mr.grn_number = (
                     SELECT g3.grn_number FROM grn g3
                     WHERE (g3.po_number = i.po_number
                        OR g3.waybill_number = (
                            SELECT w3.ewb_number FROM waybills w3
                            WHERE w3.document_number = i.invoice_number
                              AND w3.org_id = i.org_id LIMIT 1))
                       AND g3.org_id = i.org_id LIMIT 1)
                  OR mr.po_number = i.po_number)
                   AND mr.org_id = i.org_id LIMIT 1) AS mrn_drive_file_id
            FROM invoices i
            LEFT JOIN purchase_orders po
                ON po.po_number = i.po_number AND po.org_id = i.org_id
            {where}
            ORDER BY i.{col} {direction} NULLS LAST
            LIMIT :limit OFFSET :offset
        """),
        params).mappings().all()
    return {
        "total_count": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
        "invoices": [dict(r) for r in rows],
    }


# ── ITC summary ───────────────────────────────────────────────────────────────

@app.get("/itc-summary")
def itc_summary(
    db: Session = Depends(get_db_for_request),
    date_from: Optional[str] = Query(default=None),
    date_to: Optional[str] = Query(default=None),
):
    filters, params = [], {}
    if date_from:
        filters.append("i.invoice_date >= :date_from"); params["date_from"] = date_from
    if date_to:
        filters.append("i.invoice_date <= :date_to"); params["date_to"] = date_to
    where = ("AND " + " AND ".join(filters)) if filters else ""
    rows = db.execute(
        text(f"""
            SELECT li.line_item_id, li.hsn_code, li.amount, li.business_use_percent,
                   li.line_tax_rate_percent, i.invoice_id, i.vendor_name,
                   i.taxable_amount, i.total_gst_amount,
                   hp.confidence AS hsn_status
            FROM line_items li
            JOIN invoices i ON i.invoice_id = li.invoice_id
            LEFT JOIN hsn_profile_codes hp
                ON hp.org_id = li.org_id AND hp.code = li.hsn_code
            WHERE i.status NOT IN ('FAILED', 'PLACEHOLDER') {where}
        """),
        params).mappings().all()
    return compute_itc_summary([dict(r) for r in rows])


@app.get("/analytics/itc-trend")
def analytics_itc_trend(ctx: dict = Depends(get_request_context)):
    if not bq_client.is_configured():
        return {"bq_configured": False, "months": []}
    return {"bq_configured": True,
            "months": bq_client.query_itc_trend(str(ctx["org_id"]))}

@app.get("/analytics/vendor-reliability")
def analytics_vendor_reliability(ctx: dict = Depends(get_request_context)):
    if not bq_client.is_configured():
        return {"bq_configured": False, "vendors": []}
    return {"bq_configured": True,
            "vendors": bq_client.query_vendor_reliability(str(ctx["org_id"]))}


# ── Training exports ──────────────────────────────────────────────────────────

class _TrainingExportBody(BaseModel):
    invoice_id: str
    source_type: Optional[str] = None
    extraction_method: Optional[str] = None
    confidence: Optional[float] = None
    extracted_fields: dict = {}
    line_items: list = []
    verification_checks: dict = {}
    any_check_failed: bool = False
    verification_note: Optional[str] = None

@app.post("/training-exports", status_code=201)
def create_training_export(
    body: _TrainingExportBody,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    exists = db.execute(
        text("SELECT 1 FROM invoices WHERE invoice_id = CAST(:iid AS uuid)"),
        {"iid": body.invoice_id}).fetchone()
    if not exists:
        raise HTTPException(404, "Invoice not found")
    result = db.execute(
        text("""
            INSERT INTO training_exports (
              org_id, invoice_id, source_type, extraction_method, confidence,
              extracted_fields, line_items, verification_checks,
              any_check_failed, verification_note
            ) VALUES (
              CAST(:org_id AS uuid), CAST(:invoice_id AS uuid),
              :source_type, :extraction_method, :confidence,
              CAST(:extracted_fields AS jsonb), CAST(:line_items AS jsonb),
              CAST(:verification_checks AS jsonb),
              :any_check_failed, :verification_note
            ) RETURNING export_id
        """),
        {
            "org_id": ctx["org_id"], "invoice_id": body.invoice_id,
            "source_type": body.source_type, "extraction_method": body.extraction_method,
            "confidence": body.confidence,
            "extracted_fields": json.dumps(body.extracted_fields),
            "line_items": json.dumps(body.line_items),
            "verification_checks": json.dumps(body.verification_checks),
            "any_check_failed": body.any_check_failed,
            "verification_note": body.verification_note,
        })
    export_id = str(result.scalar())
    log_activity(
        db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
        action="training_export_created", entity_type="invoice",
        entity_id=body.invoice_id,
        summary=f"Verified and exported (checks_failed={body.any_check_failed})")
    return {"export_id": export_id}

@app.get("/training-exports")
def list_training_exports(
    db: Session = Depends(get_db_for_request),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    failed_only: bool = Query(default=False),
):
    filters, params = [], {"limit": page_size, "offset": (page - 1) * page_size}
    if failed_only:
        filters.append("any_check_failed = true")
    where = ("WHERE " + " AND ".join(filters)) if filters else ""
    total = db.execute(
        text(f"SELECT COUNT(*) FROM training_exports {where}"), params).scalar()
    rows = db.execute(
        text(f"SELECT export_id, invoice_id, source_type, extraction_method, confidence, "
             f"extracted_fields, line_items, verification_checks, any_check_failed, "
             f"verification_note, created_at FROM training_exports {where} "
             f"ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
        params).mappings().all()
    return {
        "total_count": total, "page": page, "page_size": page_size,
        "total_pages": max(1, -(-total // page_size)),
        "exports": [dict(r) for r in rows],
    }


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str, db: Session = Depends(get_db_for_request)):
    row = db.execute(
        text("SELECT * FROM invoices WHERE invoice_id = :iid"),
        {"iid": invoice_id}).mappings().fetchone()
    if not row:
        raise HTTPException(404, "Invoice not found")
    items = db.execute(
        text("SELECT line_item_id, description, hsn_code, quantity, rate, amount, "
             "line_tax_rate_percent, business_use_percent, itc_claimable, itc_reason "
             "FROM line_items WHERE invoice_id = :iid ORDER BY line_item_id"),
        {"iid": invoice_id}).mappings().all()
    return {**dict(row), "line_items": [dict(i) for i in items]}


# ── Multi-folder registration ─────────────────────────────────────────────────

class _DriveFoldersBody(BaseModel):
    folder_type: str
    folder_id: str

@app.put("/org/drive-folders")
def set_drive_folder_multi(
    body: _DriveFoldersBody,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    if body.folder_type not in _VALID_FOLDER_TYPES:
        raise HTTPException(400, f"folder_type must be one of {sorted(_VALID_FOLDER_TYPES)}")
    try:
        folder_id = _extract_drive_folder_id(body.folder_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    prior = db.execute(
        text("SELECT folder_id FROM org_drive_folders "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = :ftype"),
        {"oid": ctx["org_id"], "ftype": body.folder_type}).fetchone()
    prior_folder_id = prior[0] if prior else None
    try:
        db.execute(
            text("INSERT INTO org_drive_folders (org_id, folder_type, folder_id) "
                 "VALUES (CAST(:oid AS uuid), :ftype, :fid) "
                 "ON CONFLICT (org_id, folder_type) DO UPDATE SET folder_id = EXCLUDED.folder_id"),
            {"oid": ctx["org_id"], "ftype": body.folder_type, "fid": folder_id})
    except Exception:
        db.rollback()
        raise HTTPException(409, "This Drive folder is already registered for this type.")
    if body.folder_type == "invoices":
        db.execute(
            text("UPDATE orgs SET drive_folder_id = :fid WHERE org_id = :oid"),
            {"fid": folder_id, "oid": ctx["org_id"]})
    log_activity(
        db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
        action="settings_update", entity_type="drive_folder", entity_id=folder_id,
        field_name=f"drive_folder_id[{body.folder_type}]",
        old_value=prior_folder_id, new_value=folder_id,
        summary=f"{body.folder_type} Drive folder set to {folder_id}")
    return {"org_id": ctx["org_id"],
            "folder_type": body.folder_type, "folder_id": folder_id}

@app.get("/org/drive-folders")
def get_drive_folders_multi(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    rows = db.execute(
        text("SELECT folder_type, folder_id, last_synced_at FROM org_drive_folders "
             "WHERE org_id = CAST(:oid AS uuid)"),
        {"oid": ctx["org_id"]}).mappings().all()
    by_type = {
        r["folder_type"]: {
            "folder_id": r["folder_id"],
            "last_synced_at": r["last_synced_at"],
        }
        for r in rows
    }
    return {
        "org_id": ctx["org_id"],
        "folders": {t: by_type.get(t) for t in sorted(_VALID_FOLDER_TYPES)},
    }


# ── PO sync ───────────────────────────────────────────────────────────────────

@app.post("/purchase-orders/sync")
def sync_purchase_orders(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    row = db.execute(
        text("SELECT folder_id FROM org_drive_folders "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = 'purchase_orders'"),
        {"oid": ctx["org_id"]}).fetchone()
    folder_id = row[0] if row else None
    if not folder_id:
        raise HTTPException(400, "No Purchase Order Drive folder registered.")
    po_schema = core_pipeline.load_schema(PO_SCHEMA_PATH)
    already_processed = po_store.get_processed_drive_ids(db, ctx["org_id"])
    try:
        results = sync_org_po_folder(
            db, ctx["org_id"], folder_id, core_po_extractor, drive_connector,
            po_schema, str(UPLOAD_DIR), already_processed, po_store.save_po_row)
    except Exception as e:
        raise HTTPException(500, f"PO sync failed: {e}")
    db.execute(
        text("UPDATE org_drive_folders SET last_synced_at = now() "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = 'purchase_orders'"),
        {"oid": ctx["org_id"]})
    # Create placeholder invoice rows for POs with no matching invoice yet
    pos_synced = db.execute(
        text("SELECT po_number FROM purchase_orders WHERE org_id = CAST(:oid AS uuid)"),
        {"oid": ctx["org_id"]}).fetchall()
    placeholders = 0
    for (po_num,) in pos_synced:
        if po_num:
            pid = save_placeholder_invoice(
                db, ctx["org_id"], po_number=po_num, source_label="PO sync")
            if pid:
                placeholders += 1
    return {"folder_id": folder_id, "new_files_processed": len(results),
            "placeholders_created": placeholders, "results": results}

@app.get("/purchase-orders")
def list_purchase_orders(
    db: Session = Depends(get_db_for_request),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    total = db.execute(text("SELECT COUNT(*) FROM purchase_orders")).scalar()
    rows = db.execute(
        text("SELECT po_id, file_name, po_number, po_date, vendor_name, vendor_gstin, "
             "total_amount, status, confidence, processed_at "
             "FROM purchase_orders ORDER BY processed_at DESC "
             "LIMIT :limit OFFSET :offset"),
        {"limit": page_size, "offset": (page - 1) * page_size}).mappings().all()
    return {"total_count": total, "page": page, "page_size": page_size,
            "total_pages": max(1, -(-total // page_size)),
            "purchase_orders": [dict(r) for r in rows]}

@app.get("/purchase-orders/{po_id}")
def get_purchase_order(po_id: str, db: Session = Depends(get_db_for_request)):
    row = db.execute(
        text("SELECT * FROM purchase_orders WHERE po_id = :pid"),
        {"pid": po_id}).mappings().fetchone()
    if not row:
        raise HTTPException(404, "Purchase order not found")
    items = db.execute(
        text("SELECT po_line_item_id, description, hsn_code, quantity, unit, rate, amount "
             "FROM po_line_items WHERE po_id = :pid ORDER BY po_line_item_id"),
        {"pid": po_id}).mappings().all()
    return {**dict(row), "line_items": [dict(i) for i in items]}


# ── Exceptions ────────────────────────────────────────────────────────────────

@app.get("/exceptions")
def list_exceptions_route(
    db: Session = Depends(get_db_for_request),
    ctx: dict = Depends(get_request_context),
    status: Optional[str] = Query(default=None),
    exception_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    if status and status not in {"open", "resolved", "ignored"}:
        raise HTTPException(400, f"Invalid status '{status}'")
    return exception_store.list_exceptions(
        db, ctx["org_id"], status, exception_type, page, page_size)

class _ExceptionResolveBody(BaseModel):
    status: str
    resolution_note: Optional[str] = None

@app.patch("/exceptions/{exception_id}")
def resolve_exception_route(
    exception_id: str, body: _ExceptionResolveBody,
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    if body.status not in ("resolved", "ignored"):
        raise HTTPException(400, "status must be 'resolved' or 'ignored'")
    ok = exception_store.resolve_exception(
        db, ctx["org_id"], exception_id, ctx["user_id"],
        body.status, body.resolution_note)
    if not ok:
        raise HTTPException(404, "Exception not found")
    log_activity(
        db, ctx["org_id"], actor_type="user", actor_id=ctx["user_id"],
        action="exception_resolve", entity_type="exception", entity_id=exception_id,
        new_value=body.status, summary=f"Exception marked {body.status}")
    return {"exception_id": exception_id, "status": body.status}


# ── S19: Supply chain reconciliation ─────────────────────────────────────────

@app.post("/supply-chain/reconcile")
def run_supply_chain_reconcile(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    """Runs all 9 cross-document checks and writes results to exceptions table.
    Clears all open exceptions first, then inserts fresh results.
    Call after any folder sync to keep exceptions current."""
    invoices = [dict(r) for r in db.execute(text(
        "SELECT invoice_id, invoice_number, po_number, invoice_date, "
        "total_amount, vendor_id "
        "FROM invoices WHERE status NOT IN ('FAILED', 'PLACEHOLDER')"
    )).mappings().all()]
    pos = [dict(r) for r in db.execute(text(
        "SELECT po_id, po_number, requested_transport_mode, incoterm, "
        "total_amount, vendor_id FROM purchase_orders"
    )).mappings().all()]
    wbs = [dict(r) for r in db.execute(text(
        "SELECT waybill_id, ewb_number, ewb_date, ewb_valid_until, "
        "document_number, transport_mode_label, vendor_id FROM waybills"
    )).mappings().all()]
    grns = [dict(r) for r in db.execute(text(
        "SELECT grn_id, grn_number, grn_date, waybill_number, po_number, vendor_id, "
        "total_quantity_ordered, total_quantity_received, rejection_rate_pct FROM grn"
    )).mappings().all()]
    mrs = [dict(r) for r in db.execute(text(
        "SELECT mrn_id, mrn_number, grn_number, po_number, vendor_id, "
        "return_reason, total_quantity_returned FROM material_returns"
    )).mappings().all()]
    for inv in invoices:
        inv["invoice_id"] = str(inv["invoice_id"])

    exceptions = sc_reconciliation.run_supply_chain_reconciliation(
        invoices, pos, wbs, grns, mrs)

    # Clear all open supply-chain exceptions before inserting fresh ones
    db.execute(
        text("DELETE FROM exceptions "
             "WHERE org_id = CAST(:oid AS uuid) AND status = 'open'"),
        {"oid": ctx["org_id"]})
    n = exception_store.insert_exceptions(db, ctx["org_id"], exceptions)
    db.commit()
    log_activity(
        db, ctx["org_id"], actor_type="ai", action="supply_chain_reconcile",
        entity_type="reconciliation",
        summary=f"{n} supply-chain exceptions written")
    return {
        "exceptions_written": n,
        "invoices_checked": len(invoices),
        "pos_checked": len(pos),
        "waybills_checked": len(wbs),
        "grns_checked": len(grns),
        "mrs_checked": len(mrs),
    }


# ── S17: Waybill routes ───────────────────────────────────────────────────────

@app.post("/waybills/sync")
def sync_waybills(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    row = db.execute(
        text("SELECT folder_id FROM org_drive_folders "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = 'waybills'"),
        {"oid": ctx["org_id"]}).fetchone()
    if not row or not row[0]:
        raise HTTPException(400, "No Waybill Drive folder registered.")
    waybill_schema = core_pipeline.load_schema(WAYBILL_SCHEMA_PATH)
    already_processed = waybill_store.get_processed_drive_ids(db, ctx["org_id"])
    try:
        results = sync_org_waybill_folder(
            db, ctx["org_id"], row[0], core_waybill_extractor, drive_connector,
            waybill_schema, str(UPLOAD_DIR), already_processed,
            waybill_store.save_waybill_row)
    except Exception as e:
        raise HTTPException(500, f"Waybill sync failed: {e}")
    db.execute(
        text("UPDATE org_drive_folders SET last_synced_at = now() "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = 'waybills'"),
        {"oid": ctx["org_id"]})
    return {"new_files_processed": len(results), "results": results}

@app.get("/waybills")
def list_waybills_route(
    db: Session = Depends(get_db_for_request),
    ctx: dict = Depends(get_request_context),
    limit: int = Query(default=100, ge=1, le=500),
):
    return waybill_store.list_waybills(ctx["org_id"], limit=limit)

@app.get("/waybills/{waybill_id}")
def get_waybill_route(waybill_id: str, ctx: dict = Depends(get_request_context)):
    rec = waybill_store.get_waybill(ctx["org_id"], waybill_id)
    if not rec:
        raise HTTPException(404, "Waybill not found")
    return rec


# ── S17: GRN routes ───────────────────────────────────────────────────────────

@app.post("/grn/sync")
def sync_grn(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    row = db.execute(
        text("SELECT folder_id FROM org_drive_folders "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = 'grn'"),
        {"oid": ctx["org_id"]}).fetchone()
    if not row or not row[0]:
        raise HTTPException(400, "No GRN Drive folder registered.")
    grn_schema = core_pipeline.load_schema(GRN_SCHEMA_PATH)
    already_processed = grn_store.get_processed_drive_ids(db, ctx["org_id"])
    try:
        results = sync_org_grn_folder(
            db, ctx["org_id"], row[0], core_grn_extractor, drive_connector,
            grn_schema, str(UPLOAD_DIR), already_processed, grn_store.save_grn_row)
    except Exception as e:
        raise HTTPException(500, f"GRN sync failed: {e}")
    db.execute(
        text("UPDATE org_drive_folders SET last_synced_at = now() "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = 'grn'"),
        {"oid": ctx["org_id"]})
    return {"new_files_processed": len(results), "results": results}

@app.get("/grn")
def list_grn_route(
    db: Session = Depends(get_db_for_request),
    ctx: dict = Depends(get_request_context),
    limit: int = Query(default=100, ge=1, le=500),
):
    return grn_store.list_grns(ctx["org_id"], limit=limit)

@app.get("/grn/{grn_id}")
def get_grn_route(grn_id: str, ctx: dict = Depends(get_request_context)):
    rec = grn_store.get_grn(ctx["org_id"], grn_id)
    if not rec:
        raise HTTPException(404, "GRN not found")
    return rec


# ── S17: Material Return routes ───────────────────────────────────────────────

@app.post("/material-returns/sync")
def sync_material_returns(
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    row = db.execute(
        text("SELECT folder_id FROM org_drive_folders "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = 'material_return'"),
        {"oid": ctx["org_id"]}).fetchone()
    if not row or not row[0]:
        raise HTTPException(400, "No Material Return Drive folder registered.")
    mr_schema = core_pipeline.load_schema(MR_SCHEMA_PATH)
    already_processed = material_return_store.get_processed_drive_ids(db, ctx["org_id"])
    try:
        results = sync_org_material_return_folder(
            db, ctx["org_id"], row[0], core_mr_extractor, drive_connector,
            mr_schema, str(UPLOAD_DIR), already_processed,
            material_return_store.save_mr_row)
    except Exception as e:
        raise HTTPException(500, f"Material return sync failed: {e}")
    db.execute(
        text("UPDATE org_drive_folders SET last_synced_at = now() "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = 'material_return'"),
        {"oid": ctx["org_id"]})
    return {"new_files_processed": len(results), "results": results}

@app.get("/material-returns")
def list_material_returns_route(
    db: Session = Depends(get_db_for_request),
    ctx: dict = Depends(get_request_context),
    limit: int = Query(default=100, ge=1, le=500),
):
    return material_return_store.list_material_returns(ctx["org_id"], limit=limit)

@app.get("/material-returns/{mrn_id}")
def get_material_return_route(mrn_id: str, ctx: dict = Depends(get_request_context)):
    rec = material_return_store.get_material_return(ctx["org_id"], mrn_id)
    if not rec:
        raise HTTPException(404, "Material return not found")
    return rec


# ── S17: Vendor scorecard ─────────────────────────────────────────────────────

@app.get("/vendors/scorecard")
def get_vendor_scorecard(
    db: Session = Depends(get_db_for_request),
    ctx: dict = Depends(get_request_context),
):
    rows = db.execute(
        text("""
            SELECT vs.vendor_id, v.vendor_name, vs.score, vs.grade,
                   vs.quality_rate, vs.on_time_rate, vs.accuracy_rate,
                   vs.transport_compliance_rate, vs.avg_advance_pct,
                   vs.total_invoices, vs.total_grns, vs.total_returns,
                   vs.flags, vs.last_calculated_at
            FROM vendor_scores vs
            JOIN vendors v ON v.vendor_id = vs.vendor_id
            WHERE vs.org_id = CAST(:oid AS uuid) ORDER BY vs.score DESC
        """),
        {"oid": ctx["org_id"]}).mappings().all()
    return [dict(r) for r in rows]

@app.get("/vendors/{vendor_id}/score")
def get_vendor_score(
    vendor_id: str,
    db: Session = Depends(get_db_for_request),
    ctx: dict = Depends(get_request_context),
):
    row = db.execute(
        text("SELECT vs.*, v.vendor_name, v.vendor_gstin "
             "FROM vendor_scores vs "
             "JOIN vendors v ON v.vendor_id = vs.vendor_id "
             "WHERE vs.org_id = CAST(:oid AS uuid) "
             "AND vs.vendor_id = CAST(:vid AS uuid)"),
        {"oid": ctx["org_id"], "vid": vendor_id}).mappings().fetchone()
    if not row:
        raise HTTPException(404, "Vendor score not found")
    return dict(row)

@app.post("/vendors/{vendor_id}/score/recalculate")
def recalculate_vendor_score(
    vendor_id: str,
    db: Session = Depends(get_db_for_request),
    ctx: dict = Depends(get_request_context),
):
    try:
        return vendor_score_store.compute_and_save_vendor_score(
            db, ctx["org_id"], vendor_id)
    except Exception as e:
        raise HTTPException(500, f"Score calculation failed: {e}")


# ── Debug ─────────────────────────────────────────────────────────────────────

@app.get("/debug/drive-files")
def debug_drive_files(
    folder_type: str = Query(default="invoices"),
    ctx: dict = Depends(get_request_context),
    db: Session = Depends(get_db_for_request),
):
    row = db.execute(
        text("SELECT folder_id FROM org_drive_folders "
             "WHERE org_id = CAST(:oid AS uuid) AND folder_type = :ftype"),
        {"oid": ctx["org_id"], "ftype": folder_type}).fetchone()
    if not row or not row[0]:
        raise HTTPException(400, f"No folder registered for type '{folder_type}'")
    files = drive_connector.list_folder_files(row[0])
    return {"folder_type": folder_type, "folder_id": row[0],
            "file_count": len(files), "files": files}