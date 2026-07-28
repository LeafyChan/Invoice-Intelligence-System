"""
extractor.py
============
Turns raw OCR text OR a page image into structured invoice JSON.

Two entry points:
  extract_from_text(text, schema)    -> for digital_text / ocr_printed pages
  extract_from_image(image, schema)  -> for needs_vision_ai pages (handwritten,
                                          messy scans, stamps, non-standard layouts)

TWO PROVIDERS, SPLIT BY TASK:
  - extract_from_text  -> Groq (gpt-oss-120b), json_object mode.
  - extract_from_image -> Gemini (gemini-2.5-flash-lite), vision path.

TEXT PRE-PROCESSING (before any API call):
  1. Blank check  — under 50 chars → skip API, return stub.
  2. Compress     — collapse whitespace runs, deduplicate repeated header/footer
                    lines (common in multi-page PDFs). Typically halves token count.
  3. Head + tail  — if still over MAX_INPUT_CHARS after compression, keep first
                    HEAD_CHARS + last TAIL_CHARS with an explicit separator in
                    between. This preserves BOTH the invoice header (vendor, line
                    items) AND the footer (payment terms, incoterms, delivery
                    address) — critical for S17 supply-chain fields. The dropped
                    middle is almost always repeated line-item boilerplate.

RATE LIMITING / RETRY:
  Exponential backoff on 429 / RESOURCE_EXHAUSTED. Daily-quota errors fail fast
  (no retries) since waiting won't help until tomorrow's reset.

DEMO_MODE: set INVOICE_OCR_DEMO_MODE=1 to run regex-based extraction with no
  API calls — useful for local dev without keys.
"""

import json
import os
import re
import sys
import time

from PIL import Image

DEMO_MODE = os.environ.get("INVOICE_OCR_DEMO_MODE", "1") == "1"

GEMINI_MODEL_NAME = "gemini-2.5-flash-lite"
GROQ_MODEL_NAME   = "llama-3.3-70b-versatile"

MIN_SECONDS_BETWEEN_CALLS = {
    "gemini": 4.5,
    "groq":   2.5,
}

MAX_RETRIES             = 5
INITIAL_BACKOFF_SECONDS = 15

# Token budget constants
MIN_MEANINGFUL_CHARS = 50
MAX_INPUT_CHARS      = 12_000
HEAD_CHARS           = 7_000   # header, vendor block, line items
TAIL_CHARS           = 5_000   # payment terms, incoterms, delivery address, totals

_RATE_LIMIT_MARKERS = (
    "429", "RESOURCE_EXHAUSTED", "quota", "rate limit", "RateLimit",
    "rate_limit_exceeded",
)
_DAILY_QUOTA_MARKERS = ("PerDay", "per day", "RPD", "daily")

_last_call_time: dict[str, float] = {"gemini": 0.0, "groq": 0.0}


# ── Rate limiting ─────────────────────────────────────────────────────────────

def _throttle(provider: str):
    elapsed   = time.monotonic() - _last_call_time[provider]
    remaining = MIN_SECONDS_BETWEEN_CALLS[provider] - elapsed
    if remaining > 0:
        time.sleep(remaining)
    _last_call_time[provider] = time.monotonic()


def _is_rate_limit_error(e: Exception) -> bool:
    return any(m in str(e) for m in _RATE_LIMIT_MARKERS)


def _is_daily_quota_error(e: Exception) -> bool:
    return _is_rate_limit_error(e) and any(m in str(e) for m in _DAILY_QUOTA_MARKERS)


def _call_with_retry(provider: str, fn, *args):
    backoff    = INITIAL_BACKOFF_SECONDS
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        _throttle(provider)
        try:
            return fn(*args)
        except Exception as e:
            last_error = e
            if _is_daily_quota_error(e):
                print(f"   [{provider} daily quota exhausted] {e}", file=sys.stderr)
                raise
            if _is_rate_limit_error(e) and attempt < MAX_RETRIES:
                print(
                    f"   [{provider} rate limit hit, attempt {attempt}/{MAX_RETRIES} "
                    f"— waiting {backoff}s] {e}",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                backoff *= 2
                continue
            print(f"   [{provider} call failed] {e}", file=sys.stderr)
            raise
    raise last_error


# ── Prompt ────────────────────────────────────────────────────────────────────

EXTRACTION_INSTRUCTIONS_TEMPLATE = """You are extracting structured data from an invoice, which may be an
Indian GST invoice OR a foreign/non-standard invoice. Return ONLY a JSON
object, no markdown fences, no commentary.

Required fields (use null if genuinely not present, never guess):
{required_fields}

Optional fields (include if visible, else null):
{optional_fields}

TAX NORMALIZATION (important - invoices use inconsistent terminology):
- Indian invoices may show CGST + SGST (intra-state) or just IGST (inter-state).
  Map these directly to cgst_amount / sgst_amount / igst_amount.
- Some invoices just say "GST" or "Tax" with one combined number and no
  CGST/SGST/IGST split. In that case: put the full tax amount into
  total_gst_amount, and leave cgst_amount/sgst_amount/igst_amount as null.
  Do NOT guess a 50/50 CGST/SGST split if the invoice doesn't show one.
- Some invoices say "VAT" instead of GST. Treat VAT the same way as a
  combined "Tax" line: put the amount into total_gst_amount.
- Whatever the invoice actually calls its tax line (e.g. "GST", "VAT",
  "Tax", "Sales Tax", "IGST @18%"), record that exact label text in
  tax_label_raw. If there are multiple tax lines, join their labels with
  "; ". If there is no tax line at all, set tax_label_raw to null.
- total_gst_amount should always be the sum of all tax shown on the
  invoice, however it's labeled, even when cgst/sgst/igst are null.
- If a tax percentage is printed anywhere near the tax line (e.g.
  "VAT @ 12%", "GST 18%", "IGST(18%)", "Tax Rate: 5%"), extract that
  number into tax_rate_percent as a plain number (12, 18, 5 - no "%"
  sign). This applies regardless of which tax label is used (GST, VAT,
  IGST, Sales Tax, etc.) - it is not GST-specific. If multiple tax lines
  show different rates (e.g. CGST 9% + SGST 9%), use the combined/
  effective rate if one is printed, otherwise the single rate that
  applies to the combined tax line. If no percentage is printed anywhere
  on the invoice, set tax_rate_percent to null - do not calculate or
  infer it from total_gst_amount / taxable_amount, since rounding in the
  source numbers makes a back-calculated rate unreliable as a compliance
  figure.

CURRENCY:
- Detect the currency symbol or code printed on the invoice (e.g. INR, Rs,
  Rs., USD, $, EUR, £) and put a short code in currency_code (use "INR" for
  Rs/Rs./₹, "USD" for $, "EUR" for €, "GBP" for £, or the literal text if you
  genuinely can't tell). If no currency is shown at all, set it to null.
- Still extract all amounts as plain numbers exactly as printed, regardless
  of currency. Do not convert or guess an exchange rate.

GENERAL RULES:
- vendor_name and buyer_name are ONLY the company/individual name itself —
  typically the first line under a "Seller:"/"Bill From:"/"From:" heading
  (vendor) or a "Client:"/"Bill To:"/"To:" heading (buyer). NEVER include
  the address, city, state, PIN code, "Tax Id:"/GSTIN line, phone, or email
  in vendor_name/buyer_name, even though those usually appear directly below
  the name in the same visual block. If the name spans a genuine multi-word
  legal name (e.g. "TechVision Distributors Pvt Ltd"), include the whole
  name but stop there — do not continue onto the next line just because it's
  part of the same address block.
- In a two-column layout (e.g. "Seller:" / "Client:" side by side), treat
  each column as fully separate: never let text from one column's address
  or trailing lines bleed into the other column's name field.
- vendor_gstin and buyer_gstin must be exactly as printed (15 characters, no
  spaces). If the invoice is foreign and has no GSTIN, leave it null.
- All amounts as plain numbers (no currency symbols, no commas).
- invoice_date in DD-MM-YYYY.
- line_items as a list of objects: {{description, hsn_code, quantity, rate, amount, tax_rate, tax_amount, gross_amount}}.
  - rate: unit price before tax.
  - amount: net line total (quantity x rate, before tax).
  - tax_rate: percentage e.g. 18.0. Null if not printed — do NOT back-calculate.
  - tax_amount: tax currency amount on this line. Null if only shown at bill level.
  - gross_amount: amount + tax_amount. Null if tax_amount is null.
- If the document is illegible or you are not confident in a field, set it
  to null rather than guessing. Null is always preferable to a guessed value.
- NOTE: If you see a line like "[... middle of document omitted ...]" in the
  text, this means the document was long and the middle was trimmed to fit the
  token limit. The header and footer are both present — extract all fields
  normally from whatever text is visible.
"""


def _build_prompt(schema: dict) -> str:
    return EXTRACTION_INSTRUCTIONS_TEMPLATE.format(
        required_fields=", ".join(schema["required_fields"]),
        optional_fields=", ".join(schema["optional_fields"]),
    )


# ── Text pre-processing ───────────────────────────────────────────────────────

def _compress_text(text: str) -> str:
    """
    Collapse whitespace noise without losing content:
      - Strip trailing whitespace per line
      - Collapse runs of 3+ blank lines → 2 blank lines
      - Deduplicate adjacent identical lines (catches repeated page headers/footers)

    Typically halves the char count of a multi-page PDF without dropping any
    invoice data, meaning most docs never hit the head+tail truncation at all.
    """
    lines      = [l.rstrip() for l in text.splitlines()]
    compressed = []
    blank_run  = 0
    prev_nonblank = None
    for line in lines:
        if line == "":
            blank_run += 1
            if blank_run <= 2:
                compressed.append(line)
        else:
            blank_run = 0
            if line == prev_nonblank:
                continue   # skip repeated header/footer line
            prev_nonblank = line
            compressed.append(line)
    return "\n".join(compressed)


def _prepare_text(raw: str) -> tuple[str | None, str]:
    """
    Returns (None, stub_reason) if text is too short to extract from,
    or (prepared_text, "") ready to send to the model.

    Strategy:
      1. Blank check
      2. Compress
      3. If still over MAX_INPUT_CHARS: head + tail sample (never tail-only,
         because payment terms / incoterms / delivery address live at the end)
    """
    stripped = (raw or "").strip()
    if len(stripped) < MIN_MEANINGFUL_CHARS:
        return None, (
            f"OCR returned {len(stripped)} chars — too short to extract. "
            "Page may be blank, image-only, or a cover sheet."
        )

    compressed = _compress_text(stripped)
    if len(compressed) < len(stripped):
        print(
            f"   [compressed {len(stripped)} → {len(compressed)} chars]",
            file=sys.stderr,
        )

    if len(compressed) <= MAX_INPUT_CHARS:
        return compressed, ""

    # Head + tail: keep both ends, drop the middle (repeated line-item rows)
    head      = compressed[:HEAD_CHARS]
    tail      = compressed[-TAIL_CHARS:]
    separator = (
        "\n\n[... middle of document omitted to fit token limit — "
        "header, line items, and footer terms are preserved above/below ...]\n\n"
    )
    result = head + separator + tail
    print(
        f"   [head+tail: {len(compressed)} → {len(result)} chars "
        f"(kept first {HEAD_CHARS} + last {TAIL_CHARS})]",
        file=sys.stderr,
    )
    return result, ""


# ── API callers ───────────────────────────────────────────────────────────────

def _call_groq_text(prompt: str, document_text: str, schema: dict) -> dict:
    from groq import Groq
    client   = Groq()
    response = client.chat.completions.create(
        model=GROQ_MODEL_NAME,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user",   "content": f"--- DOCUMENT TEXT ---\n{document_text}"},
        ],
        response_format={"type": "json_object"},
    )
    return _clean_json_response(response.choices[0].message.content)


def _call_gemini_text(prompt: str, document_text: str) -> dict:
    from google import genai
    client   = genai.Client()
    response = client.models.generate_content(
        model=GEMINI_MODEL_NAME,
        contents=f"{prompt}\n\n--- DOCUMENT TEXT ---\n{document_text}",
    )
    return _clean_json_response(response.text)


def _call_gemini_vision(prompt: str, image: Image.Image) -> dict:
    from google import genai
    client   = genai.Client()
    response = client.models.generate_content(
        model=GEMINI_MODEL_NAME,
        contents=[prompt, image],
    )
    return _clean_json_response(response.text)


def _clean_json_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.lower().startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as first_error:
        repaired = re.sub(r",(\s*[\]}])", r"\1", raw)
        repaired = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", repaired)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            raise first_error


# ── Stubs ─────────────────────────────────────────────────────────────────────

def _demo_stub(reason: str, schema: dict) -> dict:
    stub = {f: None for f in schema["required_fields"] + schema["optional_fields"]}
    stub["_extraction_note"] = f"DEMO_MODE stub — {reason}."
    return stub


def _skip_stub(reason: str, schema: dict) -> dict:
    stub = {f: None for f in schema["required_fields"] + schema["optional_fields"]}
    stub["_extraction_note"] = reason
    return stub


# ── Demo regex parser (no API key needed) ─────────────────────────────────────

_DEMO_FIELD_PATTERNS = {
    "vendor_name":    r"(?:^|\n)([A-Z][A-Za-z .&]+(?:Ltd|Limited|Pvt Ltd|Traders|Enterprises|Stores|GmbH|Inc|Mart|Co))\n",
    "vendor_gstin":   r"GSTIN:\s*([0-9A-Z]{15})",
    "invoice_number": r"Invoice No:\s*([A-Za-z0-9\-/]+)",
    "invoice_date":   r"Invoice Date:\s*([0-9./-]+)",
    "place_of_supply":r"Place of Supply:\s*([A-Za-z ]+)",
    "buyer_name":     r"Bill To:\s*([A-Za-z0-9 .&]+)",
    "buyer_gstin":    r"Buyer GSTIN:\s*([0-9A-Z]{15})",
    "taxable_amount": r"Taxable (?:Amount|Value):\s*([0-9.,]+)",
    "cgst_amount":    r"CGST[^:]*:\s*([0-9.,]+)",
    "sgst_amount":    r"SGST[^:]*:\s*([0-9.,]+)",
    "igst_amount":    r"IGST[^:]*:\s*([0-9.,]+)",
    "total_amount":   r"Total Amount:\s*([0-9.,]+)",
}

_DEMO_TAX_LABEL_PATTERNS = [
    ("Total GST", r"Total GST\b[^:\n]*:\s*([0-9.,]+)"),
    ("GST",       r"\bGST(?!IN)\b[^:\n]*:\s*([0-9.,]+)"),
    ("VAT",       r"\bVAT\b[^:\n]*:\s*([0-9.,]+)"),
    ("Sales Tax", r"Sales Tax\b[^:\n]*:\s*([0-9.,]+)"),
    ("Tax",       r"\bTax\b[^:\n]*:\s*([0-9.,]+)"),
]

_DEMO_TAX_RATE_PATTERNS = [
    r"Total GST[^%\n]*?\(?\s*(\d{1,2}(?:\.\d+)?)\s*%",
    r"\bGST(?!IN)\b[^%\n]*?\(?\s*(\d{1,2}(?:\.\d+)?)\s*%",
    r"\bVAT\b[^%\n]*?\(?\s*(\d{1,2}(?:\.\d+)?)\s*%",
    r"\bIGST\b[^%\n]*?\(?\s*(\d{1,2}(?:\.\d+)?)\s*%",
    r"Sales Tax[^%\n]*?\(?\s*(\d{1,2}(?:\.\d+)?)\s*%",
    r"Tax Rate[:\s]*(\d{1,2}(?:\.\d+)?)\s*%",
    r"\bTax\b[^%\n]*?\(?\s*(\d{1,2}(?:\.\d+)?)\s*%",
]

_DEMO_CURRENCY_PATTERNS = [
    ("INR", r"(?:₹|Rs\.?\s|INR)"),
    ("USD", r"(?:\$|USD)"),
    ("EUR", r"(?:€|EUR)"),
    ("GBP", r"(?:£|GBP)"),
]


def _demo_text_parser(document_text: str, schema: dict) -> dict:
    result = {f: None for f in schema["required_fields"] + schema["optional_fields"]}
    for field, pattern in _DEMO_FIELD_PATTERNS.items():
        m = re.search(pattern, document_text)
        if m:
            result[field] = m.group(1).strip()
    if result.get("cgst_amount") or result.get("sgst_amount") or result.get("igst_amount"):
        parts = [result.get("cgst_amount"), result.get("sgst_amount"), result.get("igst_amount")]
        total = sum(float(p) for p in parts if p) or None
        if total:
            result["total_gst_amount"] = f"{total:.2f}"
        result["tax_label_raw"] = "CGST/SGST/IGST"
    else:
        for label, pattern in _DEMO_TAX_LABEL_PATTERNS:
            m = re.search(pattern, document_text)
            if m:
                result["total_gst_amount"] = m.group(1).strip()
                result["tax_label_raw"]     = label
                break
    for code, pattern in _DEMO_CURRENCY_PATTERNS:
        if re.search(pattern, document_text):
            result["currency_code"] = code
            break
    for pattern in _DEMO_TAX_RATE_PATTERNS:
        m = re.search(pattern, document_text, re.IGNORECASE)
        if m:
            result["tax_rate_percent"] = m.group(1).strip()
            break
    result["_extraction_note"] = "DEMO_MODE regex stand-in — no live API call."
    return result


# ── Public entry points ───────────────────────────────────────────────────────

def extract_from_text(document_text: str, schema: dict) -> dict:
    prompt = _build_prompt(schema)

    if DEMO_MODE:
        return _demo_text_parser(document_text, schema)

    # Pre-process: blank check → compress → head+tail if needed
    prepared, skip_reason = _prepare_text(document_text)
    if prepared is None:
        print(f"   [skipping API call — {skip_reason}]", file=sys.stderr)
        return _skip_stub(skip_reason, schema)

    # Groq → Gemini fallback
    if os.environ.get("GROQ_API_KEY"):
        try:
            return _call_with_retry("groq", _call_groq_text, prompt, prepared, schema)
        except Exception as groq_error:
            print(
                f"   [Groq failed, falling back to Gemini] {groq_error}",
                file=sys.stderr,
            )
    try:
        return _call_with_retry("gemini", _call_gemini_text, prompt, prepared)
    except Exception as e:
        return _demo_stub(f"both providers failed ({e})", schema)


def extract_from_image(image: Image.Image, schema: dict) -> dict:
    prompt = _build_prompt(schema)
    if DEMO_MODE:
        return _demo_stub(
            "set INVOICE_OCR_DEMO_MODE=0 and configure GEMINI_API_KEY to run live",
            schema,
        )
    try:
        return _call_with_retry("gemini", _call_gemini_vision, prompt, image)
    except Exception as e:
        return _demo_stub(f"vision call failed ({e})", schema)