"""로그인 확인 (open-questions B2). Neon Auth(관리형 Better Auth)가 발급한 JWT를 검증한다.

- NEON_AUTH_BASE_URL이 있으면 'neon' 모드: Authorization: Bearer <JWT> 필수. JWKS({base}/.well-known/jwks.json)
  의 EdDSA 공개키로 서명·만료를 확인하고, 토큰의 sub를 사용자 ID로 쓴다.
- 없으면 'dev' 모드(로컬·테스트): X-User-Id 헤더로 구분한다 (없으면 dev-user).
"""

from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit

import jwt

from app.config import get_settings

ALGORITHMS = ["EdDSA"]
LEEWAY_SECONDS = 30


class AuthError(Exception):
    pass


def auth_mode() -> str:
    return "neon" if get_settings().neon_auth_base_url else "dev"


@lru_cache
def _jwks_client(base_url: str) -> jwt.PyJWKClient:
    # 공개키는 캐시하고, 모르는 kid가 오면 다시 받아 온다 (키 교체 대비)
    return jwt.PyJWKClient(f"{base_url.rstrip('/')}/.well-known/jwks.json", cache_keys=True)


def _origin(base_url: str) -> str:
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}"


class BannedUser(AuthError):
    pass


def verify(token: str) -> dict[str, Any]:
    """서명·만료·발급자·대상을 확인한 JWT 내용. 실패하면 AuthError.

    Neon Auth 토큰은 iss와 aud가 모두 Auth 도메인의 origin이다 (2026-10 실측).
    """
    base = get_settings().neon_auth_base_url
    origin = _origin(base)
    try:
        key = _jwks_client(base).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=ALGORITHMS,
            leeway=LEEWAY_SECONDS,
            audience=origin,
            issuer=origin,
            options={"require": ["sub", "exp", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError(str(exc)) from exc
    if claims.get("banned"):
        raise BannedUser("차단된 계정")
    return claims
