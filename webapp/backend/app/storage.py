import os
import uuid
import requests

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
BUCKET = "invoices"


def is_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
    }


def upload_file(org_id: str, original_filename: str, file_bytes: bytes,
                content_type: str = "application/octet-stream") -> str:
    safe_name = f"{uuid.uuid4()}_{original_filename}"
    path = f"{BUCKET}/{org_id}/{safe_name}"
    url = f"{SUPABASE_URL}/storage/v1/object/{path}"
    headers = {**_headers(), "Content-Type": content_type}
    r = requests.post(url, headers=headers, data=file_bytes, timeout=60)
    if r.status_code not in (200, 201):
        raise RuntimeError(
            f"Supabase Storage upload failed (HTTP {r.status_code}): {r.text[:300]}"
        )
    return path


def get_signed_url(storage_path: str, expires_in: int = 3600) -> str:
    url = f"{SUPABASE_URL}/storage/v1/object/sign/{storage_path}"
    r = requests.post(
        url,
        headers={**_headers(), "Content-Type": "application/json"},
        json={"expiresIn": expires_in},
        timeout=15,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"Signed URL generation failed (HTTP {r.status_code}): {r.text[:300]}"
        )
    data = r.json()
    signed = data.get("signedURL") or data.get("signedUrl")
    if not signed:
        raise RuntimeError(f"No signedURL in Supabase response: {data}")
    return f"{SUPABASE_URL}{signed}" if signed.startswith("/") else signed