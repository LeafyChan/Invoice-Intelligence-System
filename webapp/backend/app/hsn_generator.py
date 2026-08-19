import os
import sys
import json
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from pathlib import Path
_core_parent = os.environ.get("CORE_PIPELINE_PATH", str(Path(__file__).parent.parent.parent.parent))
sys.path.insert(0, str(Path(_core_parent) / "core"))
import extractor  

DEMO_MODE = os.environ.get("INVOICE_OCR_DEMO_MODE", "1") == "1"
GROQ_MODEL_NAME = extractor.GROQ_MODEL_NAME
_MASTER_HSN_PATH = Path(__file__).parent / "config" / "hsn_master.json"
_SYSTEM_PROMPT = """You are a GST/HSN classification assistant for an Indian SME.

Given a one-sentence description of a business, produce a list of HSN
(goods) and SAC (services) codes that business would NORMALLY encounter
on its PURCHASE invoices (what it buys, not necessarily what it sells -
e.g. a furniture shop buys wood, hardware, machinery, software licenses,
not just sells furniture).

For every code, decide if it belongs in:
  - "expected": codes you are reasonably confident are a normal purchase
    for this business. Use the real 4-8 digit HSN/SAC code (not a vague
    category name).
  - "ambiguous": codes that COULD be a normal business purchase OR could
    just as easily be a personal/non-business item, a fixed asset rather
    than a consumable, or could be raw material in this business's
    specific case but a finished good in general (e.g. a furniture shop
    buying "digital display panels" - raw material if incorporated into a
    product sold to customers, a personal/fixed-asset purchase if not).
    For each ambiguous code, give a one-sentence "reason" explaining what
    the ambiguity actually is, written for a business owner deciding
    on a real invoice, not a generic disclaimer.

Be conservative: if you are not genuinely confident a code is correct for
this specific business, put it in "ambiguous" rather than "expected" -
overclaiming confidence is worse than asking a human to double check.
Do not invent a code if you do not know a real one for that category -
omit it instead of guessing.

Respond with ONLY a JSON object, no other text:
{
  "expected_codes": [{"code": "...", "code_type": "HSN"|"SAC", "description": "..."}],
  "ambiguous_codes": [{"code": "...", "code_type": "HSN"|"SAC", "description": "...", "reason": "..."}]
}
"""

_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "expected_codes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "code_type": {"type": "string", "enum": ["HSN", "SAC"]},
                    "description": {"type": "string"},
                },
                "required": ["code", "code_type", "description"],
                "additionalProperties": False,
            },
        },
        "ambiguous_codes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "code_type": {"type": "string", "enum": ["HSN", "SAC"]},
                    "description": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["code", "code_type", "description", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["expected_codes", "ambiguous_codes"],
    "additionalProperties": False,
}

def _retrieve_top_hsn_candidates(business_description: str, top_k: int = 15) -> list:
    if not _MASTER_HSN_PATH.exists():
        return []
    
    with open(_MASTER_HSN_PATH, "r", encoding="utf-8") as f:
        catalog = json.load(f)
        
    descriptions = [item["description"] for item in catalog]
    descriptions.append(business_description) # Add query to corpus
    
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(descriptions)
    
    # Compute similarity between query (last item) and all catalog items
    cosine_similarities = cosine_similarity(tfidf_matrix[-1], tfidf_matrix[:-1]).flatten()
    
    # Get top_k indices sorted by score
    top_indices = cosine_similarities.argsort()[::-1][:top_k]
    
    return [catalog[i] for i in top_indices if cosine_similarities[i] > 0.05]

def _call_groq(business_description: str) -> dict:
    from groq import Groq

    candidates = _retrieve_top_hsn_candidates(business_description, top_k=20)
    candidates_text = json.dumps(candidates, indent=2)

    rag_system_prompt = _SYSTEM_PROMPT + f"""

---
RELEVANT OFFICIAL HSN/SAC CANDIDATES DATABASE (Select ONLY from these matching codes where applicable, or use your knowledge base only if strictly certain):
{candidates_text}
"""

    client = Groq()  
    response = client.chat.completions.create(
        model=GROQ_MODEL_NAME,
        messages=[
            {"role": "system", "content": rag_system_prompt},
            {"role": "user", "content": f"Business description: {business_description}"},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "hsn_profile",
                "strict": True,
                "schema": _JSON_SCHEMA,
            },
        },
    )
    return extractor._clean_json_response(response.choices[0].message.content)


def _demo_stub(business_description: str) -> dict:
    """No GROQ_API_KEY / sandboxed environment: returns clearly-marked
    placeholder data, same philosophy as extractor._demo_stub - the rest of
    the feature (save/merge/apply/UI) stays fully exercisable without a
    live key, and nothing here is presented as real classification."""
    return {
        "expected_codes": [
            {
                "code": "0000",
                "code_type": "HSN",
                "description": (
                    f"[DEMO MODE - not a real classification] Placeholder for: "
                    f"{business_description.strip()[:80]}"
                ),
            },
        ],
        "ambiguous_codes": [],
    }


def generate_hsn_profile(business_description: str) -> dict:
    business_description = (business_description or "").strip()
    if not business_description:
        raise ValueError("business_description is empty - nothing to generate from")

    if DEMO_MODE or not os.environ.get("GROQ_API_KEY"):
        return _demo_stub(business_description)

    return extractor._call_with_retry("groq", _call_groq, business_description)