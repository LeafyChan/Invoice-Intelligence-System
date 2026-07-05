"""grn_extractor.py — Goods Receipt Note extraction (Session 17)"""
from __future__ import annotations
import json, re, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ocr_engine  # noqa: E402
import extractor   # noqa: E402


def _run_ocr(file_path: str) -> str:
    pages = ocr_engine.read_pdf(file_path)
    return "\n\n".join(p.raw_text for p in pages if p.raw_text)

SCHEMA_PATH = Path(__file__).parent / "config" / "grn_schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

SYSTEM_PROMPT = """You are an expert at extracting structured data from Goods Receipt Notes (GRN).
Extract all fields exactly as they appear. For line items, compute quantity_accepted = quantity_received - quantity_rejected if not explicitly stated.
Dates in YYYY-MM-DD. Return ONLY valid JSON — no markdown, no explanation."""

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
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        return {"_parse_error": raw}
    return _normalise(data)


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