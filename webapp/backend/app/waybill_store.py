"""waybill_store.py — DB operations for waybills (Session 17)"""
from __future__ import annotations
import json
from uuid import uuid4
from sqlalchemy import text
from .db import get_org_scoped_db


def upsert_waybill(org_id: str, data: dict, drive_file_id: str = None, file_name: str = None) -> str:
    """Insert or update waybill by ewb_number. Returns waybill_id."""
    waybill_id = str(uuid4())
    raw_data = json.dumps({k: v for k, v in data.items() if not k.startswith("_")})

    with get_org_scoped_db(org_id) as db:
        db.execute(text("""
            INSERT INTO waybills (
                waybill_id, org_id, drive_file_id, file_name,
                ewb_number, ewb_date, ewb_valid_until,
                document_type, document_number, document_date,
                supplier_gstin, supplier_name, supplier_address,
                recipient_gstin, recipient_name, recipient_address,
                place_of_dispatch, place_of_delivery,
                consignment_value, hsn_code, goods_description, quantity, unit,
                cgst_rate, sgst_rate, igst_rate,
                transport_mode, transport_mode_label,
                vehicle_number, vehicle_type,
                transporter_id, transporter_name,
                transport_document_number, transport_document_date,
                distance_km, raw_data
            ) VALUES (
                :waybill_id, :org_id, :drive_file_id, :file_name,
                :ewb_number, :ewb_date, :ewb_valid_until,
                :document_type, :document_number, :document_date,
                :supplier_gstin, :supplier_name, :supplier_address,
                :recipient_gstin, :recipient_name, :recipient_address,
                :place_of_dispatch, :place_of_delivery,
                :consignment_value, :hsn_code, :goods_description, :quantity, :unit,
                :cgst_rate, :sgst_rate, :igst_rate,
                :transport_mode, :transport_mode_label,
                :vehicle_number, :vehicle_type,
                :transporter_id, :transporter_name,
                :transport_document_number, :transport_document_date,
                :distance_km, CAST(:raw_data AS JSONB)
            )
            ON CONFLICT (drive_file_id, org_id) DO UPDATE SET
                ewb_number = EXCLUDED.ewb_number,
                ewb_date = EXCLUDED.ewb_date,
                ewb_valid_until = EXCLUDED.ewb_valid_until,
                document_type = EXCLUDED.document_type,
                document_number = EXCLUDED.document_number,
                document_date = EXCLUDED.document_date,
                supplier_gstin = EXCLUDED.supplier_gstin,
                supplier_name = EXCLUDED.supplier_name,
                supplier_address = EXCLUDED.supplier_address,
                recipient_gstin = EXCLUDED.recipient_gstin,
                recipient_name = EXCLUDED.recipient_name,
                recipient_address = EXCLUDED.recipient_address,
                place_of_dispatch = EXCLUDED.place_of_dispatch,
                place_of_delivery = EXCLUDED.place_of_delivery,
                consignment_value = EXCLUDED.consignment_value,
                hsn_code = EXCLUDED.hsn_code,
                goods_description = EXCLUDED.goods_description,
                quantity = EXCLUDED.quantity,
                unit = EXCLUDED.unit,
                cgst_rate = EXCLUDED.cgst_rate,
                sgst_rate = EXCLUDED.sgst_rate,
                igst_rate = EXCLUDED.igst_rate,
                transport_mode = EXCLUDED.transport_mode,
                transport_mode_label = EXCLUDED.transport_mode_label,
                vehicle_number = EXCLUDED.vehicle_number,
                vehicle_type = EXCLUDED.vehicle_type,
                transporter_id = EXCLUDED.transporter_id,
                transporter_name = EXCLUDED.transporter_name,
                transport_document_number = EXCLUDED.transport_document_number,
                transport_document_date = EXCLUDED.transport_document_date,
                distance_km = EXCLUDED.distance_km,
                raw_data = EXCLUDED.raw_data
        """), {
            "waybill_id": waybill_id, "org_id": org_id,
            "drive_file_id": drive_file_id, "file_name": file_name,
            **{k: data.get(k) for k in (
                "ewb_number", "ewb_date", "ewb_valid_until",
                "document_type", "document_number", "document_date",
                "supplier_gstin", "supplier_name", "supplier_address",
                "recipient_gstin", "recipient_name", "recipient_address",
                "place_of_dispatch", "place_of_delivery",
                "consignment_value", "hsn_code", "goods_description", "quantity", "unit",
                "cgst_rate", "sgst_rate", "igst_rate",
                "transport_mode", "transport_mode_label",
                "vehicle_number", "vehicle_type",
                "transporter_id", "transporter_name",
                "transport_document_number", "transport_document_date",
                "distance_km",
            )},
            "raw_data": raw_data,
        })
    return waybill_id


def list_waybills(org_id: str, limit: int = 100, offset: int = 0) -> list[dict]:
    with get_org_scoped_db(org_id) as db:
        rows = db.execute(text("""
            SELECT waybill_id, ewb_number, ewb_date, ewb_valid_until,
                   document_number, supplier_name, recipient_name,
                   transport_mode_label, vehicle_number, distance_km,
                   consignment_value, file_name, created_at
            FROM waybills
            ORDER BY ewb_date DESC NULLS LAST, created_at DESC
            LIMIT :limit OFFSET :offset
        """), {"limit": limit, "offset": offset}).fetchall()
    return [dict(r._mapping) for r in rows]


def get_waybill(org_id: str, waybill_id: str) -> dict | None:
    with get_org_scoped_db(org_id) as db:
        row = db.execute(text("""
            SELECT * FROM waybills WHERE waybill_id = CAST(:waybill_id AS UUID)
        """), {"waybill_id": waybill_id}).fetchone()
    return dict(row._mapping) if row else None

def get_processed_drive_ids(db, org_id: str) -> set:
    """Returns set of drive_file_ids already saved for this org — used by sync to skip duplicates."""
    rows = db.execute(
        text("SELECT drive_file_id FROM waybills WHERE org_id = CAST(:oid AS uuid) AND drive_file_id IS NOT NULL"),
        {"oid": org_id}
    ).fetchall()
    return {r[0] for r in rows}


def save_waybill_row(db, org_id: str, row: dict, drive_file_id: str = None, file_name: str = None) -> str:
    """Thin wrapper so supply_chain_drive_sync can call a consistent save_fn signature."""
    return upsert_waybill(org_id, row, drive_file_id=drive_file_id or row.get("drive_file_id"), file_name=file_name or row.get("file_name"))