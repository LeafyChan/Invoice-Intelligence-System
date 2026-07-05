"""
app/po_store.py
================
Persistence for purchase_orders / po_line_items. Mirrors the conventions
visible in main.py's direct SQL for invoices/line_items: CAST(:x AS uuid)
for every UUID bind (not Postgres's ::uuid syntax — see main.py's log_activity
docstring for why), org_id threaded explicitly into every INSERT despite RLS
already enforcing isolation (defense-in-depth, same posture as schema.sql's
own comments), and dedup on (org_id, drive_file_id) via the table's UNIQUE
constraint.

is_already_processed mirrors app.invoice_store.is_already_processed's
implied signature (used in drive_sync.py as
`is_already_processed(db, org_id, f["id"])`) so po_gstr2b_drive_sync.py's
caller (main.py) can fetch a set of already-processed drive_file_ids the
same way it already does for invoices, OR call this per-file if preferred.
Both are provided since po_gstr2b_drive_sync.py's already_processed_drive_ids
parameter expects a pre-fetched set (cheaper than one query per file).
"""

import json
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

PO_INSERT_FIELDS = (
    "po_number", "po_date", "vendor_name", "vendor_gstin", "place_of_supply",
    "delivery_date", "taxable_amount", "cgst_amount", "sgst_amount",
    "igst_amount", "total_gst_amount", "total_amount", "notes_raw",
)


def _to_iso(d) -> str | None:
    """Convert DD-MM-YYYY or DD/MM/YYYY to YYYY-MM-DD for Postgres DATE columns."""
    if not d:
        return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(d).strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None  # unrecognised format — let it be null rather than error


def is_already_processed(db: Session, org_id: str, drive_file_id: str) -> bool:
    if not drive_file_id:
        return False
    row = db.execute(
        text("SELECT 1 FROM purchase_orders WHERE org_id = CAST(:oid AS uuid) "
             "AND drive_file_id = :fid LIMIT 1"),
        {"oid": org_id, "fid": drive_file_id}).fetchone()
    return row is not None


def get_processed_drive_ids(db: Session, org_id: str) -> set:
    """Fetches all drive_file_ids already in purchase_orders for this org in
    one query — the cheap dedup path for a sync cycle covering many files,
    vs. one is_already_processed() call per file."""
    rows = db.execute(
        text("SELECT drive_file_id FROM purchase_orders "
             "WHERE org_id = CAST(:oid AS uuid) AND drive_file_id IS NOT NULL"),
        {"oid": org_id}).fetchall()
    return {r[0] for r in rows}


def save_po_row(db: Session, org_id: str, row: dict, source_type: str = "drive",
                storage_path: str = None) -> str:
    """
    Inserts one PO (one page's worth of extracted data — mirrors
    pipeline.process_single_pdf's per-page row shape) plus its line items.
    Returns the new po_id.
    """
    line_items = row.get("line_items") or []
    if isinstance(line_items, str):
        try:
            line_items = json.loads(line_items)
        except (json.JSONDecodeError, TypeError):
            line_items = []

    params = {f: row.get(f) for f in PO_INSERT_FIELDS}
    params.update({
        "oid": org_id, "stype": source_type, "dfid": row.get("drive_file_id"),
        "spath": storage_path, "fname": row.get("file_name"), "page": row.get("page"),
        "method": row.get("extraction_method"), "conf": row.get("confidence"),
        "status": row.get("status"), "issues": row.get("issues"),
    })

    # Convert DD-MM-YYYY → YYYY-MM-DD for Postgres DATE columns
    params["po_date"]       = _to_iso(params.get("po_date"))
    params["delivery_date"] = _to_iso(params.get("delivery_date"))

    result = db.execute(
        text(
            "INSERT INTO purchase_orders ("
            " org_id, source_type, drive_file_id, storage_path, file_name, page,"
            " extraction_method, confidence, status, issues,"
            " po_number, po_date, vendor_name, vendor_gstin, place_of_supply,"
            " delivery_date, taxable_amount, cgst_amount, sgst_amount,"
            " igst_amount, total_gst_amount, total_amount, notes_raw"
            ") VALUES ("
            " CAST(:oid AS uuid), :stype, :dfid, :spath, :fname, :page,"
            " :method, :conf, :status, :issues,"
            " :po_number, :po_date, :vendor_name, :vendor_gstin, :place_of_supply,"
            " :delivery_date, :taxable_amount, :cgst_amount, :sgst_amount,"
            " :igst_amount, :total_gst_amount, :total_amount, :notes_raw"
            ") ON CONFLICT (org_id, drive_file_id) DO NOTHING RETURNING po_id"
        ),
        params)
    po_id_raw = result.scalar()
    if po_id_raw is None:
        return None  # duplicate — already synced
    po_id = str(po_id_raw)

    for item in line_items:
        if not isinstance(item, dict):
            continue
        db.execute(
            text(
                "INSERT INTO po_line_items "
                "(org_id, po_id, description, hsn_code, quantity, unit, rate, amount) "
                "VALUES (CAST(:oid AS uuid), CAST(:pid AS uuid), :desc, :hsn, :qty, :unit, :rate, :amt)"
            ),
            {"oid": org_id, "pid": po_id, "desc": item.get("description"),
             "hsn": item.get("hsn_code"), "qty": item.get("quantity"),
             "unit": item.get("unit"), "rate": item.get("rate"), "amt": item.get("amount")})

    db.commit()
    return po_id


def list_pos_for_org(db: Session, org_id: str) -> list[dict]:
    """Used by reconciliation.py's caller to fetch all POs for matching —
    deliberately returns plain dicts (not ORM objects), matching the
    DB-agnostic input shape reconciliation.match_invoices_to_pos expects."""
    rows = db.execute(
        text("SELECT po_id, po_number, vendor_name, vendor_gstin, total_amount, "
             "status, file_name FROM purchase_orders WHERE org_id = CAST(:oid AS uuid)"),
        {"oid": org_id}).mappings().all()
    return [dict(r) for r in rows]