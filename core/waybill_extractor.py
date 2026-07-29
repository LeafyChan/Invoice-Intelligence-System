from __future__ import annotations
import json, re, sys, os
from pathlib import Path

try:
    import json_repair as _json_repair
    _HAS_JSON_REPAIR = True
except ImportError:
    _HAS_JSON_REPAIR = False

sys.path.insert(0, str(Path(__file__).parent))
import ocr_engine  
import extractor   

def _run_ocr(file_path: str) -> str:
    pages = ocr_engine.read_pdf(file_path)
    return "\n\n".join(p.raw_text for p in pages if p.raw_text)

SCHEMA_PATH = Path(__file__).parent / "config" / "waybill_schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())

_REQUIRED = SCHEMA.get("required_fields", [])
_OPTIONAL = SCHEMA.get("optional_fields", [])
_ALL_FIELDS = ", ".join(f'"{f}"' for f in _REQUIRED + _OPTIONAL)

TRANSPORT_MODE_MAP = {"1": "Road", "2": "Rail", "3": "Air", "4": "Ship",
                      "road": "Road", "rail": "Rail", "air": "Air", "ship": "Ship"}

SYSTEM_PROMPT = (
    "You are an expert at extracting structured data from Indian E-Way Bills (Form GST EWB-01).\n\n"
    "Return ONLY a single flat JSON object with these keys (omit keys not present in the document):\n"
    + _ALL_FIELDS + "\n\n"
    "Rules:\n"
    "- transport_mode: numeric code only (1=Road, 2=Rail, 3=Air, 4=Ship)\n"
    "- All dates: YYYY-MM-DD\n"
    "- GST rates: numeric percentage (18, not 0.18)\n"
    "- consignment_value, quantity, distance_km: numbers, not strings\n"
    "- No markdown fences, no explanation, no extra keys\n"
    "- Output must be valid JSON — every string value properly quoted and escaped"
)


def _build_user_message(raw_text: str) -> str:
    return (
        "Extract all E-Waybill fields from the document below.\n"
        "Return a single flat JSON object. Keys from both Part A and Part B at the top level.\n\n"
        "--- DOCUMENT ---\n"
        + raw_text +
        "\n--- END ---"
    )


def extract_waybill(file_path: str, org_id: str) -> dict:
    raw_text = _run_ocr(file_path)

    if extractor.DEMO_MODE:
        return extractor._demo_stub("set INVOICE_OCR_DEMO_MODE=0 and configure API keys to run live", SCHEMA)

    user_msg = _build_user_message(raw_text)

    groq_key_present = bool(os.environ.get("GROQ_API_KEY"))
    if groq_key_present:
        try:
            raw_json = extractor._call_with_retry(
                "groq", extractor._call_groq_text, SYSTEM_PROMPT, user_msg, None)
            if isinstance(raw_json, dict):
                raw_json["_raw_text"] = raw_text
                return _parse_and_normalise_dict(raw_json)
            data = _parse_and_normalise(raw_json if isinstance(raw_json, str) else json.dumps(raw_json))
            data["_raw_text"] = raw_text
            return data
        except Exception as e:
            print(f"   [Groq failed, falling back to Gemini for waybill] {e}", file=sys.stderr)

    try:
        raw_json = extractor._call_with_retry("gemini", extractor._call_gemini_text, SYSTEM_PROMPT, user_msg)
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
        return _normalise(data)
    except json.JSONDecodeError:
        pass
    if _HAS_JSON_REPAIR:
        try:
            repaired = _json_repair.repair_json(clean, return_objects=True)
            if isinstance(repaired, dict) and repaired:
                print("   [waybill_extractor] JSON repaired successfully", file=sys.stderr)
                return _normalise(repaired)
        except Exception as repair_err:
            print(f"   [waybill_extractor] json_repair failed: {repair_err}", file=sys.stderr)
    return {"_parse_error": raw}


def _normalise(data: dict) -> dict:
    tm = str(data.get("transport_mode", "")).lower()
    if tm in TRANSPORT_MODE_MAP:
        data["transport_mode_label"] = TRANSPORT_MODE_MAP[tm]
        try:
            data["transport_mode"] = int(tm)
        except ValueError:
            reverse = {"road": 1, "rail": 2, "air": 3, "ship": 4}
            data["transport_mode"] = reverse.get(tm)
    for f in ("consignment_value", "quantity", "distance_km",
              "cgst_rate", "sgst_rate", "igst_rate"):
        if f in data and data[f] is not None:
            try:
                data[f] = float(data[f])
            except (ValueError, TypeError):
                data[f] = None

    return data