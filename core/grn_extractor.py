"""grn_extractor.py — Goods Receipt Note extraction (Session 17)"""
from __future__ import annotations
import json, re, sys, os
from pathlib import Path

try:
    import json_repair as _json_repair
    _HAS_JSON_REPAIR = True
except ImportError:
    _HAS_JSON_REPAIR = False

sys.path.insert(0, str(Path(__file__).parent))
import ocr_engine  # noqa: E402
import extractor   # noqa: E402


def _run_ocr(file_path: str) -> str:
    pages = ocr_engine.read_pdf(file_path)
    return "\n\n".join(p.raw_text for p in pages if p.raw_text)

SCHEMA_PATH = Path(__file__).parent / "config" / "grn_schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

SYSTEM_PROMPT = """You are an expert at extracting structured data from Goods Receipt Notes (GRN).

CRITICAL JSON RULES — violations cause downstream failures:
1. Return ONLY a single valid JSON object. No markdown fences, no explanation, no text before or after.
2. The "line_items" value MUST be a complete JSON array [...]. Every element must be a complete {...} object with its closing brace.
3. String values may contain any characters (commas, dashes, em-dashes, semicolons, slashes) — they must be properly escaped but never terminate the object early.
4. Do NOT split one item's description across multiple item_number entries.
5. Dates in YYYY-MM-DD format.
6. For line items: quantity_accepted = quantity_received - quantity_rejected if not explicitly stated.

Example of a correctly formed line item (even with punctuation in description):
{"item_number": 3, "description": "ISO 9001 — Automotive; defect RTV to be raised", "hsn_code": "28510099", "unit": "LTR", "quantity_ordered": 153.0, "quantity_received": 153.0, "quantity_accepted": 149.0, "quantity_rejected": 4.0, "remarks": "finish quarantined"}"""

def extract_grn(file_path: str, org_id: str) -> dict:
    raw_text = _run_ocr(file_path)
    schema_str = json.dumps(SCHEMA, indent=2)

    if extractor.DEMO_MODE:
        return extractor._demo_stub("set INVOICE_OCR_DEMO_MODE=0 and configure API keys to run live", SCHEMA)

    groq_key_present = bool(os.environ.get("GROQ_API_KEY"))
    if groq_key_present:
        try:
            result = extractor._call_with_retry(
                "groq", extractor._call_groq_text, SYSTEM_PROMPT, raw_text, SCHEMA)
            if isinstance(result, dict):
                result["_raw_text"] = raw_text
                return _parse_and_normalise_dict(result)
        except Exception as e:
            print(f"   [Groq failed, falling back to Gemini for GRN] {e}", file=__import__("sys").stderr)
    try:
        raw_json = extractor._call_with_retry("gemini", extractor._call_gemini_text, SYSTEM_PROMPT, raw_text)
    except Exception as e:
        return extractor._demo_stub(f"live call failed ({e})", SCHEMA)

    raw_json = raw_json if isinstance(raw_json, str) else json.dumps(raw_json)
    data = _parse_and_normalise(raw_json)
    data["_raw_text"] = raw_text
    return data


def _parse_and_normalise_dict(data: dict) -> dict:
    return _normalise(data)


def _parse_and_normalise(raw: str) -> dict:
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()

    # Fast path — valid JSON
    try:
        data = json.loads(clean)
        return _normalise(data)
    except json.JSONDecodeError as first_err:
        pass

    # Repair path — handles Groq's common failure modes:
    #   • missing closing brace on a line_items element
    #   • orphaned keys after a prematurely closed array
    #   • trailing comma before ]
    if _HAS_JSON_REPAIR:
        try:
            repaired = _json_repair.repair_json(clean, return_objects=True)
            if isinstance(repaired, dict) and repaired:
                print("   [grn_extractor] JSON repaired successfully", file=sys.stderr)
                return _normalise(repaired)
        except Exception as repair_err:
            print(f"   [grn_extractor] json_repair failed: {repair_err}", file=sys.stderr)

    # Manual fallback — extract whatever line_items we can salvage
    salvaged = _salvage_line_items(clean)
    if salvaged:
        print("   [grn_extractor] used line_items salvage fallback", file=sys.stderr)
        return _normalise(salvaged)

    return {"_parse_error": raw}


def _salvage_line_items(raw: str) -> dict | None:
    """
    Last-resort repair: the model sometimes emits a valid header block and
    then corrupts the line_items array (missing brace, orphaned keys).
    This function extracts the header fields and whatever complete item
    objects it can find, then reassembles a valid dict.
    """
    # Pull out individual {...} objects that look like line items
    item_pattern = re.compile(
        r'\{[^{}]*"item_number"\s*:\s*\d+[^{}]*\}', re.DOTALL
    )
    items = []
    for m in item_pattern.finditer(raw):
        try:
            items.append(json.loads(m.group()))
        except json.JSONDecodeError:
            pass

    if not items:
        return None

    # Try to parse header fields by truncating at line_items
    header: dict = {}
    header_match = re.search(r'^(\{.*?)"line_items"\s*:', raw, re.DOTALL)
    if header_match:
        try:
            header = json.loads(header_match.group(1) + '"line_items": []}')
        except json.JSONDecodeError:
            pass

    header["line_items"] = items
    return header


def _normalise(data: dict) -> dict:
    # Auto-compute totals from line items if missing
    items = data.get("line_items", [])
    if items and not data.get("total_quantity_received"):
        data["total_quantity_ordered"]  = sum(float(i.get("quantity_ordered",  0) or 0) for i in items)
        data["total_quantity_received"] = sum(float(i.get("quantity_received", 0) or 0) for i in items)
        data["total_quantity_rejected"] = sum(float(i.get("quantity_rejected", 0) or 0) for i in items)
        data["total_quantity_accepted"] = sum(float(i.get("quantity_accepted", 0) or 0) for i in items)

    # Ensure quantity_accepted on each line item
    for item in items:
        if item.get("quantity_accepted") is None:
            recv = float(item.get("quantity_received", 0) or 0)
            rej  = float(item.get("quantity_rejected", 0) or 0)
            item["quantity_accepted"] = recv - rej

    return data