import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import extractor

PO_EXTRACTION_INSTRUCTIONS_TEMPLATE = """You are extracting structured data from a Purchase Order (PO) document —
an internal order document a buyer sends to a vendor, NOT an invoice. Return
ONLY a JSON object, no markdown fences, no commentary.

Required fields (use null if genuinely not present, never guess):
{required_fields}

Optional fields (include if visible, else null):
{optional_fields}

GENERAL RULES:
- po_number is the PO's own identifying number (often labeled "PO Number",
  "Purchase Order No.", "Order Ref"), NOT an invoice number — a PO document
  never has an invoice number on it.
- vendor_name is ONLY the vendor/supplier company name itself — the party
  the order is being placed WITH, typically under a "Vendor:", "Supplier:",
  or "To:" heading. Never include address, GSTIN, phone, or email lines in
  vendor_name, even though they usually appear directly below it.
- vendor_gstin must be exactly as printed (15 characters, no spaces). Null
  if not shown — many smaller vendors' POs omit it even though the eventual
  invoice will include it.
- All amounts as plain numbers (no currency symbols, no commas).
- po_date in DD-MM-YYYY.
- delivery_date: keep as the exact text printed (e.g. "17-Jun-2026" or
  "within 2 weeks of order") — do not normalize this one, since POs often
  state delivery as a relative timeframe rather than a hard date.
- incoterm_raw: copy the EXACT delivery/shipment term as printed on the PO,
  even if it is not a standard code (e.g. "Ex-Warehouse Hyderabad",
  "Franco Destination", "Door Delivery"). Never null if any delivery term exists.
- incoterm: the closest matching Incoterms 2020 code from this list —
  EXW, FCA, CPT, CIP, DAP, DPU, DDP, FAS, FOB, CFR, CIF.
  Indian domestic equivalents map as follows:
    "Ex-Works" / "Ex-Factory" / "Ex-Warehouse" → EXW
    "Door Delivery" / "Franco" / "Delivered" → DDP
    "C&F" / "CNF" → CFR
    "CIF" → CIF
    "FOB" → FOB
  If no standard Incoterms 2020 code matches, use "DOMESTIC".
  Null only if NO delivery/shipment term appears anywhere on the PO.
- Tax handling: same normalization as invoices — CGST+SGST for intra-state,
  IGST for inter-state, combined "GST"/"Tax" line goes into
  total_gst_amount with cgst/sgst/igst left null. Do not guess a 50/50
  CGST/SGST split if the PO doesn't show one explicitly.
- line_items as a list of objects: {{description, hsn_code, quantity, unit,
  rate, amount}}. unit is the unit of measure as printed (e.g. "Pcs", "Box",
  "Kg", "Service") — null if not shown. amount is quantity × rate.
- notes_raw: any delivery instructions, special terms, or remarks printed
  on the PO outside the main item table and the standard header fields —
  verbatim, or null if there are none.
- If the document is illegible, low quality, or you are not confident in a
  field, set that field to null rather than guessing. Do not fabricate values.
"""


def _build_po_prompt(schema: dict) -> str:
    return PO_EXTRACTION_INSTRUCTIONS_TEMPLATE.format(
        required_fields=", ".join(schema["required_fields"]),
        optional_fields=", ".join(schema["optional_fields"]),
    )


def extract_from_text(document_text: str, schema: dict) -> dict:
    prompt = _build_po_prompt(schema)
    if extractor.DEMO_MODE:
        return extractor._demo_stub(
            "PO extraction has no demo-mode parser; set INVOICE_OCR_DEMO_MODE=0 "
            "and configure GROQ_API_KEY/GEMINI_API_KEY to run live", schema)

    groq_key_present = bool(os.environ.get("GROQ_API_KEY"))
    if groq_key_present:
        try:
            return extractor._call_with_retry(
                "groq", extractor._call_groq_text, prompt, document_text, schema)
        except Exception as groq_error:
            print(f"   [Groq failed, falling back to Gemini for this PO] {groq_error}",
                  file=sys.stderr)
    try:
        return extractor._call_with_retry("gemini", extractor._call_gemini_text, prompt, document_text)
    except Exception as e:
        return extractor._demo_stub(f"live call failed ({e})", schema)


def extract_from_image(image, schema: dict) -> dict:
    prompt = _build_po_prompt(schema)
    if extractor.DEMO_MODE:
        return extractor._demo_stub(
            "set INVOICE_OCR_DEMO_MODE=0 and configure GEMINI_API_KEY to run live", schema)
    try:
        return extractor._call_with_retry("gemini", extractor._call_gemini_vision, prompt, image)
    except Exception as e:
        return extractor._demo_stub(f"live call failed ({e})", schema)