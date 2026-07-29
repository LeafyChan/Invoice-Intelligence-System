from __future__ import annotations
import json
from uuid import uuid4
from sqlalchemy import text
from .db import get_org_scoped_db


def upsert_grn(org_id: str, data: dict, drive_file_id: str = None, file_name: str = None) -> str:
    grn_id = str(uuid4())
    raw_data = json.dumps({k: v for k, v in data.items() if not k.startswith("_")})
    line_items = json.dumps(data.get("line_items", []))
    with get_org_scoped_db(org_id) as db:
        db.execute(text("""
            INSERT INTO grn (
                grn_id, org_id, drive_file_id, file_name,
                grn_number, grn_date, po_number, waybill_number,
                vendor_name, vendor_gstin, received_by, receipt_location,
                total_quantity_ordered, total_quantity_received,
                total_quantity_rejected, total_quantity_accepted,
                line_items, raw_data
            ) VALUES (
                :grn_id, :org_id, :drive_file_id, :file_name,
                :grn_number, :grn_date, :po_number, :waybill_number,
                :vendor_name, :vendor_gstin, :received_by, :receipt_location,
                :total_quantity_ordered, :total_quantity_received,
                :total_quantity_rejected, :total_quantity_accepted,
                CAST(:line_items AS JSONB), CAST(:raw_data AS JSONB)
            )
            ON CONFLICT (drive_file_id, org_id) DO UPDATE SET
                grn_number = EXCLUDED.grn_number,
                grn_date = EXCLUDED.grn_date,
                po_number = EXCLUDED.po_number,
                waybill_number = EXCLUDED.waybill_number,
                vendor_name = EXCLUDED.vendor_name,
                vendor_gstin = EXCLUDED.vendor_gstin,
                received_by = EXCLUDED.received_by,
                receipt_location = EXCLUDED.receipt_location,
                total_quantity_ordered = EXCLUDED.total_quantity_ordered,
                total_quantity_received = EXCLUDED.total_quantity_received,
                total_quantity_rejected = EXCLUDED.total_quantity_rejected,
                total_quantity_accepted = EXCLUDED.total_quantity_accepted,
                line_items = EXCLUDED.line_items,
                raw_data = EXCLUDED.raw_data
        """), {
            "grn_id": grn_id, "org_id": org_id,
            "drive_file_id": drive_file_id, "file_name": file_name,
            **{k: data.get(k) for k in (
                "grn_number", "grn_date", "po_number", "waybill_number",
                "vendor_name", "vendor_gstin", "received_by", "receipt_location",
                "total_quantity_ordered", "total_quantity_received",
                "total_quantity_rejected", "total_quantity_accepted",
            )},
            "line_items": line_items,
            "raw_data": raw_data,
        })
    return grn_id


def list_grns(org_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    with get_org_scoped_db(org_id) as db:
        rows = db.execute(text("""
            SELECT grn_id, grn_number, grn_date, po_number, waybill_number,
                   vendor_name, total_quantity_ordered, total_quantity_received,
                   total_quantity_rejected, total_quantity_accepted,
                   rejection_rate_pct, file_name, created_at
            FROM grn
            ORDER BY grn_date DESC NULLS LAST, created_at DESC
            LIMIT :limit OFFSET :offset
        """), {"limit": limit, "offset": offset}).fetchall()
    return [dict(r._mapping) for r in rows]


def get_grn(org_id: str, grn_id: str) -> dict | None:
    with get_org_scoped_db(org_id) as db:
        row = db.execute(text("""
            SELECT * FROM grn WHERE grn_id = CAST(:grn_id AS UUID)
        """), {"grn_id": grn_id}).fetchone()
    return dict(row._mapping) if row else None


def get_processed_drive_ids(db, org_id: str) -> set:
    rows = db.execute(
        text("""
            SELECT drive_file_id FROM grn
            WHERE org_id = CAST(:oid AS uuid)
              AND drive_file_id IS NOT NULL
              AND grn_number IS NOT NULL
        """),
        {"oid": org_id}
    ).fetchall()
    return {r[0] for r in rows}


def save_grn_row(db, org_id: str, row: dict, drive_file_id: str = None, file_name: str = None) -> str:
    return upsert_grn(
        org_id, row,
        drive_file_id=drive_file_id or row.get("drive_file_id"),
        file_name=file_name or row.get("file_name")
    )