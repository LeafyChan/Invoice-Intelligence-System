"""material_return_extractor.py — Material Return Note extraction (Session 17)"""
from __future__ import annotations
import json, re, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ocr_engine  # noqa: E402
import extractor   # noqa: E402


def _run_ocr(file_path: str) -> str:
    pages = ocr_engine.read_pdf(file_path)
    return "\n\n".join(p.raw_text for p in pages if p.raw_text)

SCHEMA_PATH = Path(__file__).parent / "config" / "material_return_schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

VALID_REASONS = {"Defective", "Wrong Item", "Excess Quantity", "Damaged in Transit", "Quality Rejection"}

SYSTEM_PROMPT = """You are an expert at extracting structured data from Material Return Notes (MRN).
Extract all fields exactly. For return_reason, map to one of: Defective / Wrong Item / Excess Quantity / Damaged in Transit / Quality Rejection.
Dates in YYYY-MM-DD. photos_attached should be boolean. Return ONLY valid JSON — no markdown."""

def extract_material_return(file_path: str, org_id: str) -> dict:
    raw_text = _run_ocr(file_path)

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
            print(f"   [Groq failed, falling back to Gemini for MRN] {e}", file=__import__("sys").stderr)
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
    # Normalise return_reason
    reason = data.get("return_reason", "")
    if reason not in VALID_REASONS:
        lower = reason.lower()
        if "defect" in lower:                             data["return_reason"] = "Defective"
        elif "wrong" in lower:                            data["return_reason"] = "Wrong Item"
        elif "excess" in lower:                           data["return_reason"] = "Excess Quantity"
        elif "transit" in lower or "damage" in lower:    data["return_reason"] = "Damaged in Transit"
        elif "quality" in lower:                          data["return_reason"] = "Quality Rejection"

    # Auto-compute total
    items = data.get("line_items", [])
    if items and not data.get("total_quantity_returned"):
        data["total_quantity_returned"] = sum(float(i.get("quantity_returned", 0) or 0) for i in items)

    return data