import re
from datetime import datetime


def _parse_amount(val) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").replace("₹", "").strip())
    except (ValueError, TypeError):
        return None


def _parse_date(val, formats: list[str]) -> datetime | None:
    if not val:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(str(val).strip(), fmt)
        except ValueError:
            continue
    return None


def _normalize_currency_token(val: str) -> str:
    v = val.strip().upper()
    mapping = {
        "RS": "INR", "RS.": "INR", "₹": "INR", "INR": "INR",
        "$": "USD", "USD": "USD",
        "€": "EUR", "EUR": "EUR",
        "£": "GBP", "GBP": "GBP",
    }
    return mapping.get(v, v)


def validate_invoice(extracted: dict, schema: dict, page_confidence: float,
                      extraction_method: str) -> dict:
    issues: list[str] = []       
    notes: list[str] = []        
    rules = schema["validation_rules"]
    thresholds = schema["confidence_thresholds"]
    if extracted.get("_extraction_note"):
        notes.append(extracted["_extraction_note"])

    if extraction_method == "needs_vision_ai":
        notes.append(
            "Source page had low OCR confidence (likely handwritten, stamped, "
            "rotated, or a degraded scan) — extracted values need a human check."
        )
    missing = [f for f in schema["required_fields"] if not extracted.get(f)]
    if missing:
        issues.append(f"Missing required field(s): {', '.join(missing)}")
    gstin_pattern = re.compile(rules["gstin_regex"])
    for gstin_field in ("vendor_gstin", "buyer_gstin"):
        val = extracted.get(gstin_field)
        if val and not gstin_pattern.match(str(val).strip()):
            issues.append(f"{gstin_field} '{val}' does not match valid GSTIN format")
    taxable = _parse_amount(extracted.get("taxable_amount"))
    gst = _parse_amount(extracted.get("total_gst_amount"))
    total = _parse_amount(extracted.get("total_amount"))
    tolerance = rules["amount_reconciliation_tolerance"]

    if taxable is not None and gst is not None and total is not None:
        expected_total = taxable + gst
        if abs(expected_total - total) > tolerance:
            issues.append(
                f"Amount mismatch: taxable ({taxable}) + GST/Tax ({gst}) = "
                f"{expected_total:.2f}, but total_amount is {total}"
            )
    elif taxable is None and gst is None and total is not None:
        pass
    cgst = _parse_amount(extracted.get("cgst_amount"))
    sgst = _parse_amount(extracted.get("sgst_amount"))
    igst = _parse_amount(extracted.get("igst_amount"))

    if cgst is not None and sgst is not None and gst is not None:
        if abs((cgst + sgst) - gst) > tolerance:
            issues.append(
                f"CGST ({cgst}) + SGST ({sgst}) does not equal total_gst_amount ({gst})"
            )
    elif igst is not None and gst is not None:
        if abs(igst - gst) > tolerance:
            issues.append(
                f"IGST ({igst}) does not equal total_gst_amount ({gst})"
            )
    invoice_date = _parse_date(extracted.get("invoice_date"), rules["date_formats"])
    if extracted.get("invoice_date") and not invoice_date:
        issues.append(f"invoice_date '{extracted.get('invoice_date')}' could not be parsed")
    elif invoice_date and (datetime.now() - invoice_date).days > rules["max_invoice_age_days"]:
        issues.append(f"invoice_date is unusually old ({invoice_date.date()})")
    currency = extracted.get("currency_code")
    if currency:
        normalized = _normalize_currency_token(str(currency))
        expected = rules.get("expected_currency", "INR")
        if normalized != expected:
            notes.append(
                f"Invoice currency detected as {currency} (not {expected}) - "
                f"amounts are being treated as {expected} per current policy; "
                f"figures are NOT converted."
            )
    has_missing_required = any(i.startswith("Missing required field") for i in issues)
    is_low_confidence = page_confidence < thresholds["needs_review_below"]
    is_unverified_source = extraction_method == "needs_vision_ai"

    if has_missing_required or is_low_confidence or is_unverified_source:
        status = "NEEDS_MANUAL_REVIEW"
    elif any("mismatch" in i or "does not equal" in i or "format" in i for i in issues):
        status = "FAILED" if len(issues) > 1 else "WARNING"
    elif issues:
        status = "WARNING"
    else:
        status = "PASSED"

    return {
        "status": status,
        "issues": notes + issues,
        "confidence": round(page_confidence, 1),
    }
