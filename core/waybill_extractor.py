"""waybill_extractor.py — E-Waybill OCR + LLM extraction (Session 17)"""
from __future__ import annotations
import json, re, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ocr_engine  # noqa: E402 — core/ocr_engine.py (exposes read_pdf)
import extractor   # noqa: E402 — reuse existing Groq/Gemini wrapper


def _run_ocr(file_path: str) -> str:
    """Collapse all pages from read_pdf into a single text string."""
    pages = ocr_engine.read_pdf(file_path)
    return "\n\n".join(p.raw_text for p in pages if p.raw_text)

SCHEMA_PATH = Path(__file__).parent / "config" / "waybill_schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

TRANSPORT_MODE_MAP = {"1": "Road", "2": "Rail", "3": "Air", "4": "Ship",
                      "road": "Road", "rail": "Rail", "air": "Air", "ship": "Ship"}

SYSTEM_PROMPT = """You are an expert at extracting structured data from Indian E-Way Bills (Form GST EWB-01).
Extract ALL fields exactly as they appear. For transport_mode, return the numeric code (1/2/3/4).
For dates, return YYYY-MM-DD. For GST rates, return as numeric percentage (e.g. 18, not 0.18).
Return ONLY valid JSON matching the schema — no markdown, no explanation."""

def extract_waybill(file_path: str, org_id: str) -> dict:
    """Full pipeline: OCR → LLM → validate → return structured dict."""
    raw_text = _run_ocr(file_path)
    schema_str = json.dumps(SCHEMA, indent=2)

    prompt = f"""Extract all E-Waybill fields from this document text.
Schema to follow:
{schema_str}

Document text:
{raw_text}

Return JSON with keys from both part_a and part_b flattened at top level."""

    if extractor.DEMO_MODE:
        return extractor._demo_stub("set INVOICE_OCR_DEMO_MODE=0 and configure API keys to run live", SCHEMA)

    groq_key_present = bool(os.environ.get("GROQ_API_KEY"))
    if groq_key_present:
        try:
            raw_json = extractor._call_with_retry(
                "groq", extractor._call_groq_text, SYSTEM_PROMPT, raw_text, SCHEMA)
            if isinstance(raw_json, dict):
                raw_json["_raw_text"] = raw_text
                return _parse_and_normalise_dict(raw_json)
        except Exception as e:
            print(f"   [Groq failed, falling back to Gemini for waybill] {e}", file=sys.stderr)
    try:
        raw_json = extractor._call_with_retry("gemini", extractor._call_gemini_text, SYSTEM_PROMPT, raw_text)
    except Exception as e:
        return extractor._demo_stub(f"live call failed ({e})", SCHEMA)

    raw_json = raw_json if isinstance(raw_json, str) else json.dumps(raw_json)
    data = _parse_and_normalise(raw_json)
    data["_raw_text"] = raw_text
    return data


def _parse_and_normalise_dict(data: dict) -> dict:
    """Normalise an already-parsed dict (from Groq path)."""
    return _normalise(data)


def _parse_and_normalise(raw: str) -> dict:
    # Strip markdown fences if present
    clean = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        return {"_parse_error": raw}

    return _normalise(data)


def _normalise(data: dict) -> dict:
    # Normalise transport_mode
    tm = str(data.get("transport_mode", "")).lower()
    if tm in TRANSPORT_MODE_MAP:
        data["transport_mode_label"] = TRANSPORT_MODE_MAP[tm]
        try:
            data["transport_mode"] = int(tm)
        except ValueError:
            reverse = {"road": 1, "rail": 2, "air": 3, "ship": 4}
            data["transport_mode"] = reverse.get(tm)

    # Coerce numerics
    for f in ("consignment_value", "quantity", "distance_km",
              "cgst_rate", "sgst_rate", "igst_rate"):
        if f in data and data[f] is not None:
            try:
                data[f] = float(data[f])
            except (ValueError, TypeError):
                data[f] = None

    return data