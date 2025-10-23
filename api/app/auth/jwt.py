"""JWT/JWKS auth guard utilities.
SPDX-License-Identifier: BUSL-1.1
"""
from __future__ import annotations

import time
from fastapi import Depends, HTTPException, status
from ..core.config import settings
import jwt


# --- JWKS client cache ---
_JWKS_CLIENT_CACHE: dict[str, tuple[object, float]] = {}


def _get_jwks_signing_key(token: str):
    if not settings.jwt_jwks_url:
        raise RuntimeError("JWKS URL not configured")
    url = settings.jwt_jwks_url
    now = time.time()
    client_tuple = _JWKS_CLIENT_CACHE.get(url)
    client = None
    if client_tuple is not None:
        c, created = client_tuple
        if now - created < max(1, int(settings.jwt_cache_ttl_seconds)):
            client = c
    if client is None:
        jwks_client = jwt.PyJWKClient(url)
        _JWKS_CLIENT_CACHE[url] = (jwks_client, now)
        client = jwks_client
    signing_key = client.get_signing_key_from_jwt(token)  # type: ignore[attr-defined]
    return signing_key.key


def auth_guard():
    from fastapi import Header

    async def _check(
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    ):
        if settings.jwt_enabled:
            if not authorization or not authorization.startswith("Bearer "):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="missing bearer token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            token = authorization.split(" ", 1)[1].strip()
            try:
                if settings.jwt_jwks_url:
                    key = _get_jwks_signing_key(token)
                    jwt.decode(
                        token,
                        key=key,
                        algorithms=settings.jwt_algorithms,
                        audience=settings.jwt_audience,
                        issuer=settings.jwt_issuer,
                        leeway=int(settings.jwt_leeway),
                    )
                else:
                    if not settings.jwt_secret:
                        raise RuntimeError("jwt_secret not configured")
                    jwt.decode(
                        token,
                        key=str(settings.jwt_secret),
                        algorithms=settings.jwt_algorithms,
                        audience=settings.jwt_audience,
                        issuer=settings.jwt_issuer,
                        leeway=int(settings.jwt_leeway),
                    )
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid bearer token",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return True
        if settings.api_key_required:
            if settings.api_key and x_api_key == settings.api_key:
                return True
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")
        return True

    return Depends(_check)


def extract_claims_from_request(request) -> dict:
    """Best-effort extraction of JWT claims from the incoming request.

    - Validates token using configured secret or JWKS if available.
    - Returns {} on any error.
    - Does not enforce auth; for use in optional ACL context mapping.
    """
    try:
        authz = None
        try:
            authz = request.headers.get("authorization") or request.headers.get("Authorization")
        except Exception:
            return {}
        if not authz or not isinstance(authz, str) or not authz.startswith("Bearer "):
            return {}
        token = authz.split(" ", 1)[1].strip()
        if settings.jwt_jwks_url:
            key = _get_jwks_signing_key(token)
            claims = jwt.decode(
                token,
                key=key,
                algorithms=settings.jwt_algorithms,
                audience=settings.jwt_audience,
                issuer=settings.jwt_issuer,
                leeway=int(settings.jwt_leeway),
                options={"verify_signature": True},
            )
            return claims if isinstance(claims, dict) else {}
        if settings.jwt_secret:
            claims = jwt.decode(
                token,
                key=str(settings.jwt_secret),
                algorithms=settings.jwt_algorithms,
                audience=settings.jwt_audience,
                issuer=settings.jwt_issuer,
                leeway=int(settings.jwt_leeway),
                options={"verify_signature": True},
            )
            return claims if isinstance(claims, dict) else {}
        # No configured validation => don't trust
        return {}
    except Exception:
        return {}
