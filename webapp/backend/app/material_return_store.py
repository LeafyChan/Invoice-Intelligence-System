"""material_return_store.py — fixed ON CONFLICT target + get_processed_drive_ids only returns successful extractions"""
from __future__ import annotations
import json
from uuid import uuid4
from sqlalchemy import text
from .db import get_org_scoped_db


def upsert_material_return(org_id: str, data: dict, drive_file_id: str = None, file_name: str = None) -> str:
    mrn_id = str(uuid4())
    raw_data = json.dumps({k: v for k, v in data.items() if not k.startswith("_")})
    line_items = json.dumps(data.get("line_items", []))
    with get_org_scoped_db(org_id) as db:
        db.execute(text("""
            INSERT INTO material_returns (
                mrn_id, org_id, drive_file_id, file_name,
                mrn_number, mrn_date, grn_number, po_number,
                vendor_name, vendor_gstin, return_reason, return_initiated_by,
                total_quantity_returned, line_items, raw_data
            ) VALUES (
                :mrn_id, :org_id, :drive_file_id, :file_name,
                :mrn_number, :mrn_date, :grn_number, :po_number,
                :vendor_name, :vendor_gstin, :return_reason, :return_initiated_by,
                :total_quantity_returned, CAST(:line_items AS JSONB), CAST(:raw_data AS JSONB)
            )
            ON CONFLICT (drive_file_id, org_id) DO UPDATE SET
                mrn_number = EXCLUDED.mrn_number,
                mrn_date = EXCLUDED.mrn_date,
                grn_number = EXCLUDED.grn_number,
                po_number = EXCLUDED.po_number,
                vendor_name = EXCLUDED.vendor_name,
                vendor_gstin = EXCLUDED.vendor_gstin,
                return_reason = EXCLUDED.return_reason,
                return_initiated_by = EXCLUDED.return_initiated_by,
                total_quantity_returned = EXCLUDED.total_quantity_returned,
                line_items = EXCLUDED.line_items,
                raw_data = EXCLUDED.raw_data
        """), {
            "mrn_id": mrn_id, "org_id": org_id,
            "drive_file_id": drive_file_id, "file_name": file_name,
            **{k: data.get(k) for k in (
                "mrn_number", "mrn_date", "grn_number", "po_number",
                "vendor_name", "vendor_gstin", "return_reason", "return_initiated_by",
                "total_quantity_returned",
            )},
            "line_items": line_items,
            "raw_data": raw_data,
        })
    return mrn_id


def list_material_returns(org_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    with get_org_scoped_db(org_id) as db:
        rows = db.execute(text("""
            SELECT mrn_id, mrn_number, mrn_date, grn_number, po_number,
                   vendor_name, return_reason, total_quantity_returned,
                   file_name, created_at
            FROM material_returns
            ORDER BY mrn_date DESC NULLS LAST, created_at DESC
            LIMIT :limit OFFSET :offset
        """), {"limit": limit, "offset": offset}).fetchall()
    return [dict(r._mapping) for r in rows]


def get_material_return(org_id: str, mrn_id: str) -> dict | None:
    with get_org_scoped_db(org_id) as db:
        row = db.execute(text("""
            SELECT * FROM material_returns WHERE mrn_id = CAST(:mrn_id AS UUID)
        """), {"mrn_id": mrn_id}).fetchone()
    return dict(row._mapping) if row else None


def get_processed_drive_ids(db, org_id: str) -> set:
    """
    Only returns drive_file_ids where mrn_number is not null.
    A null mrn_number means the extraction failed (LLM returned garbage,
    token limit hit, JSON parse error, etc). Those files are excluded from
    the skip-set so sync retries them on the next run.
    """
    rows = db.execute(
        text("""
            SELECT drive_file_id FROM material_returns
            WHERE org_id = CAST(:oid AS uuid)
              AND drive_file_id IS NOT NULL
              AND mrn_number IS NOT NULL
        """),
        {"oid": org_id}
    ).fetchall()
    return {r[0] for r in rows}


def save_mr_row(db, org_id: str, row: dict, drive_file_id: str = None, file_name: str = None) -> str:
    return upsert_material_return(
        org_id, row,
        drive_file_id=drive_file_id or row.get("drive_file_id"),
        file_name=file_name or row.get("file_name")
    )