import os
import time
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

CLERK_JWKS_URL = os.environ.get("CLERK_JWKS_URL")
if not CLERK_JWKS_URL:
    raise RuntimeError(
        "CLERK_JWKS_URL is not set. Find it in the Clerk dashboard under "
        "Configure -> API Keys -> Show JWT Public Key -> JWKS URL, looks like "
        "https://your-instance.clerk.accounts.dev/.well-known/jwks.json"
    )
ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CLERK_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
]

_jwk_client = PyJWKClient(CLERK_JWKS_URL, cache_keys=True, cache_jwk_set=True, lifespan=3600)


def _verify_token(token: str) -> dict:
    """Verifies signature + standard claims. Raises jwt exceptions on any
    failure - caller (get_current_org) converts these to HTTP 401."""
    signing_key = _jwk_client.get_signing_key_from_jwt(token)
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        options={"require": ["exp", "iat", "sub"]},
        leeway=30,
    )
    azp = payload.get("azp")
    if azp is not None and azp not in ALLOWED_ORIGINS:
        raise jwt.InvalidTokenError(f"azp claim '{azp}' not in allowed origins")

    return payload

def get_current_org(authorization: str = Header(...)) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = _verify_token(token)
    except jwt.ExpiredSignatureError:
        import logging; logging.warning("AUTH 401: token expired")
        raise HTTPException(401, "Session token expired")
    except jwt.InvalidTokenError as e:
        import logging; logging.warning(f"AUTH 401: invalid token: {e}")
        raise HTTPException(401, f"Invalid session token: {e}")

    if payload.get("sts") == "pending":
        raise HTTPException(
            403, "User has not joined an organization yet - org membership required"
        )

    org_claim = payload.get("o")
    if not org_claim or "id" not in org_claim:
        raise HTTPException(
            403, "Token has no active organization - this app requires org membership"
        )

    return {
        "org_id": org_claim["id"],          
        "user_id": payload["sub"],          
        "role": org_claim.get("rol"),       
    }