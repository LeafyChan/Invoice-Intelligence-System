import json
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session

def _parse_date(val) -> str | None:
    if not val:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(str(val).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _parse_amount(val):
    if val is None or val == "":
        return None
    try:
        return float(str(val).replace(",", "").replace("\u20b9", "").strip())
    except (ValueError, TypeError):
        return None


def _get_or_create_vendor(db: Session, org_id: str, vendor_name, vendor_gstin, invoice_date) -> str:
    if not vendor_name and not vendor_gstin:
        row = db.execute(
            text("SELECT vendor_id FROM vendors "
                 "WHERE org_id = :oid AND vendor_gstin IS NULL AND vendor_name IS NULL"),
            {"oid": org_id}).fetchone()
        if row:
            return str(row[0])
        result = db.execute(
            text("INSERT INTO vendors (org_id, vendor_gstin, vendor_name, first_seen_date, last_seen_date) "
                 "VALUES (:oid, NULL, NULL, :d, :d) RETURNING vendor_id"),
            {"oid": org_id, "d": invoice_date})
        return str(result.scalar())

    if vendor_gstin:
        row = db.execute(
            text("SELECT vendor_id FROM vendors WHERE org_id = :oid AND vendor_gstin = :g"),
            {"oid": org_id, "g": vendor_gstin}).fetchone()
    else:
        row = db.execute(
            text("SELECT vendor_id FROM vendors "
                 "WHERE org_id = :oid AND vendor_gstin IS NULL AND vendor_name = :n"),
            {"oid": org_id, "n": vendor_name}).fetchone()

    if row:
        vendor_id = row[0]
        if vendor_name:
            db.execute(
                text("UPDATE vendors SET vendor_name = COALESCE(vendor_name, :n) WHERE vendor_id = :vid"),
                {"n": vendor_name, "vid": vendor_id})
        db.execute(
            text("UPDATE vendors SET "
                 "  last_seen_date = GREATEST(COALESCE(last_seen_date, CAST(:d AS date)), COALESCE(CAST(:d AS date), last_seen_date)), "
                 "  first_seen_date = LEAST(COALESCE(first_seen_date, CAST(:d AS date)), COALESCE(CAST(:d AS date), first_seen_date)) "
                 "WHERE vendor_id = :vid"),
            {"d": invoice_date, "vid": vendor_id})
        return str(vendor_id)

    result = db.execute(
        text("INSERT INTO vendors (org_id, vendor_gstin, vendor_name, first_seen_date, last_seen_date) "
             "VALUES (:oid, :g, :n, :d, :d) RETURNING vendor_id"),
        {"oid": org_id, "g": vendor_gstin, "n": vendor_name, "d": invoice_date})
    return str(result.scalar())


def save_invoice_row(db: Session, org_id: str, row: dict, source_type: str = "upload",
                      storage_path: str = None) -> str | None:
    invoice_date = _parse_date(row.get("invoice_date"))
    vendor_id = _get_or_create_vendor(
        db, org_id, row.get("vendor_name"), row.get("vendor_gstin"), invoice_date)

    line_items_raw = row.get("line_items")
    line_items = []
    if line_items_raw:
        try:
            parsed = json.loads(line_items_raw) if isinstance(line_items_raw, str) else line_items_raw
            if isinstance(parsed, list):
                line_items = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    hsn_codes_raw = row.get("hsn_codes")
    hsn_codes_json = None
    if hsn_codes_raw:
        try:
            hsn_codes_json = json.dumps(
                json.loads(hsn_codes_raw) if isinstance(hsn_codes_raw, str) else hsn_codes_raw)
        except (json.JSONDecodeError, TypeError):
            hsn_codes_json = None

    params = {
        "org_id": org_id,
        "vendor_id": vendor_id,
        "source_type": source_type,
        "drive_file_id": row.get("drive_file_id"),
        "storage_path": storage_path,
        "file_name": row.get("file_name"),
        "page": row.get("page"),
        "extraction_method": row.get("extraction_method"),
        "confidence": row.get("confidence"),
        "status": row.get("status"),
        "issues": row.get("issues"),
        "vendor_name": row.get("vendor_name"),
        "vendor_gstin": row.get("vendor_gstin"),
        "buyer_name": row.get("buyer_name"),
        "buyer_gstin": row.get("buyer_gstin"),
        "invoice_number": row.get("invoice_number"),
        "invoice_date": invoice_date,
        "payment_due_date": _parse_date(row.get("payment_due_date")),
        "place_of_supply": row.get("place_of_supply"),
        "taxable_amount": _parse_amount(row.get("taxable_amount")),
        "cgst_amount": _parse_amount(row.get("cgst_amount")),
        "sgst_amount": _parse_amount(row.get("sgst_amount")),
        "igst_amount": _parse_amount(row.get("igst_amount")),
        "total_gst_amount": _parse_amount(row.get("total_gst_amount")),
        "total_amount": _parse_amount(row.get("total_amount")),
        "currency_code": row.get("currency_code"),
        "tax_label_raw": row.get("tax_label_raw"),
        "tax_rate_percent": _parse_amount(row.get("tax_rate_percent")),
        "po_number": row.get("po_number"),
        "hsn_codes": hsn_codes_json,
        "line_items_raw": json.dumps(line_items) if line_items else line_items_raw,
    }

    result = db.execute(
        text(
            "INSERT INTO invoices ("
            "  org_id, vendor_id, source_type, drive_file_id, storage_path, file_name, page,"
            "  extraction_method, confidence, status, issues,"
            "  vendor_name, vendor_gstin, buyer_name, buyer_gstin, invoice_number,"
            "  invoice_date, payment_due_date, place_of_supply,"
            "  taxable_amount, cgst_amount, sgst_amount, igst_amount, total_gst_amount, total_amount,"
            "  currency_code, tax_label_raw, tax_rate_percent, po_number, hsn_codes, line_items_raw"
            ") VALUES ("
            "  :org_id, :vendor_id, :source_type, :drive_file_id, :storage_path, :file_name, :page,"
            "  :extraction_method, :confidence, :status, :issues,"
            "  :vendor_name, :vendor_gstin, :buyer_name, :buyer_gstin, :invoice_number,"
            "  :invoice_date, :payment_due_date, :place_of_supply,"
            "  :taxable_amount, :cgst_amount, :sgst_amount, :igst_amount, :total_gst_amount, :total_amount,"
            "  :currency_code, :tax_label_raw, :tax_rate_percent, :po_number, :hsn_codes, :line_items_raw"
            ") ON CONFLICT (org_id, drive_file_id) DO UPDATE SET"
            "  vendor_id        = EXCLUDED.vendor_id,"
            "  source_type      = EXCLUDED.source_type,"
            "  file_name        = EXCLUDED.file_name,"
            "  page             = EXCLUDED.page,"
            "  extraction_method= EXCLUDED.extraction_method,"
            "  confidence       = EXCLUDED.confidence,"
            "  status           = EXCLUDED.status,"
            "  issues           = EXCLUDED.issues,"
            "  vendor_name      = EXCLUDED.vendor_name,"
            "  vendor_gstin     = EXCLUDED.vendor_gstin,"
            "  buyer_name       = EXCLUDED.buyer_name,"
            "  buyer_gstin      = EXCLUDED.buyer_gstin,"
            "  invoice_number   = EXCLUDED.invoice_number,"
            "  invoice_date     = EXCLUDED.invoice_date,"
            "  payment_due_date = EXCLUDED.payment_due_date,"
            "  place_of_supply  = EXCLUDED.place_of_supply,"
            "  taxable_amount   = EXCLUDED.taxable_amount,"
            "  cgst_amount      = EXCLUDED.cgst_amount,"
            "  sgst_amount      = EXCLUDED.sgst_amount,"
            "  igst_amount      = EXCLUDED.igst_amount,"
            "  total_gst_amount = EXCLUDED.total_gst_amount,"
            "  total_amount     = EXCLUDED.total_amount,"
            "  currency_code    = EXCLUDED.currency_code,"
            "  tax_label_raw    = EXCLUDED.tax_label_raw,"
            "  tax_rate_percent = EXCLUDED.tax_rate_percent,"
            "  po_number        = EXCLUDED.po_number,"
            "  hsn_codes        = EXCLUDED.hsn_codes,"
            "  line_items_raw   = EXCLUDED.line_items_raw"
            "  WHERE invoices.vendor_name IS NULL"
            "     OR invoices.status IN ('PLACEHOLDER', 'FAILED')"
            " RETURNING invoice_id"
        ),
        params,
    )
    invoice_id_raw = result.scalar()
    if invoice_id_raw is None:
        db.rollback()
        return None
    invoice_id = str(invoice_id_raw)
    db.execute(text("DELETE FROM line_items WHERE invoice_id = :iid"), {"iid": invoice_id})

    for item in line_items:
        if not isinstance(item, dict):
            continue
        db.execute(
            text("INSERT INTO line_items (org_id, invoice_id, description, hsn_code, "
                 "quantity, rate, amount, tax_rate, tax_amount, gross_amount) "
                 "VALUES (:org_id, :invoice_id, :description, :hsn_code, "
                 ":quantity, :rate, :amount, :tax_rate, :tax_amount, :gross_amount)"),
            {
                "org_id": org_id,
                "invoice_id": invoice_id,
                "description": item.get("description"),
                "hsn_code": item.get("hsn_code"),
                "quantity": _parse_amount(item.get("quantity")),
                "rate": _parse_amount(item.get("rate")),
                "amount": _parse_amount(item.get("amount")),
                "tax_rate": _parse_amount(item.get("tax_rate")),
                "tax_amount": _parse_amount(item.get("tax_amount")),
                "gross_amount": _parse_amount(item.get("gross_amount")),
            })

    total_amount = _parse_amount(row.get("total_amount"))
    db.execute(
        text("UPDATE vendors SET invoice_count = invoice_count + 1, "
             "total_amount = total_amount + :amt WHERE vendor_id = :vid"),
        {"amt": total_amount or 0, "vid": vendor_id})

    db.commit()
    return invoice_id


def save_placeholder_invoice(db: Session, org_id: str, po_number: str = None,
                              invoice_number: str = None, source_label: str = "") -> str | None:
    """
    Creates a minimal PLACEHOLDER invoice row when a PO/waybill/GRN references
    an invoice that doesn't exist yet. Returns invoice_id or None if already exists.
    When the invoices folder is synced later, save_invoice_row's ON CONFLICT UPDATE
    will fill in all the real fields automatically.
    """
    if not po_number and not invoice_number:
        return None
    existing = db.execute(
        text("SELECT invoice_id FROM invoices WHERE org_id = CAST(:oid AS uuid) AND ("
             "  (:po IS NOT NULL AND po_number = :po) OR "
             "  (:inv IS NOT NULL AND invoice_number = :inv)"
             ") LIMIT 1"),
        {"oid": org_id, "po": po_number, "inv": invoice_number}).fetchone()
    if existing:
        return None
    result = db.execute(
        text("INSERT INTO invoices (org_id, source_type, file_name, status, po_number, invoice_number) "
             "VALUES (CAST(:oid AS uuid), 'placeholder', :fname, 'PLACEHOLDER', :po, :inv) "
             "RETURNING invoice_id"),
        {"oid": org_id,
         "fname": f"[Placeholder — from {source_label}]",
         "po": po_number, "inv": invoice_number})
    db.commit()
    return str(result.scalar())


def get_line_items_for_bq(db: Session, org_id: str, invoice_id: str) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT
                li.line_item_id, li.invoice_id, li.org_id,
                li.hsn_code, li.amount, li.business_use_percent, li.line_tax_rate_percent,
                i.vendor_name, i.vendor_gstin,
                i.taxable_amount, i.total_gst_amount,
                i.invoice_date, i.status,
                hp.confidence AS hsn_status
            FROM line_items li
            JOIN invoices i ON i.invoice_id = li.invoice_id
            LEFT JOIN hsn_profile_codes hp
                ON hp.org_id = li.org_id AND hp.code = li.hsn_code
            WHERE li.invoice_id = :iid AND li.org_id = :oid
        """),
        {"iid": invoice_id, "oid": org_id}).mappings().all()
    return [dict(r) for r in rows]


def is_already_processed(db: Session, org_id: str, drive_file_id: str) -> bool:
    """Returns True only if the file was SUCCESSFULLY extracted (vendor_name present).
    Blank/PLACEHOLDER/FAILED rows return False so they get retried on next sync."""
    if not drive_file_id:
        return False
    row = db.execute(
        text("SELECT 1 FROM invoices "
             "WHERE org_id = :oid AND drive_file_id = :did "
             "  AND vendor_name IS NOT NULL "
             "  AND status NOT IN ('PLACEHOLDER', 'FAILED') LIMIT 1"),
        {"oid": org_id, "did": drive_file_id}).fetchone()
    return row is not None