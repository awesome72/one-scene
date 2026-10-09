import time
from collections.abc import Iterator
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from app import auth
from app.config import get_settings

ORIGIN = "https://ep-test.neonauth.example.aws.neon.tech"
BASE = f"{ORIGIN}/neondb/auth"
KEY = Ed25519PrivateKey.generate()
OTHER_KEY = Ed25519PrivateKey.generate()


def token(sub: str = "user-123", *, key: Ed25519PrivateKey = KEY, exp_in: int = 900,
          iss: str = ORIGIN, aud: str = ORIGIN, **extra: object) -> str:
    """실제 Neon Auth 토큰 모양: iss와 aud가 모두 Auth 도메인 origin."""
    now = int(time.time())
    claims = {"sub": sub, "exp": now + exp_in, "iat": now, "iss": iss, "aud": aud, **extra}
    return jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": "k1"})


def bearer(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def neon_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(get_settings(), "neon_auth_base_url", BASE)
    fake_jwks = SimpleNamespace(
        get_signing_key_from_jwt=lambda _t: SimpleNamespace(key=KEY.public_key())
    )
    monkeypatch.setattr(auth, "_jwks_client", lambda _base: fake_jwks)
    yield


def test_dev_mode_uses_header(client: TestClient) -> None:
    assert auth.auth_mode() == "dev"
    sid = client.post("/sessions", json={}, headers={"X-User-Id": "alice"}).json()["id"]
    assert client.get(f"/sessions/{sid}", headers={"X-User-Id": "alice"}).status_code == 200


def test_neon_mode_requires_token(client: TestClient, neon_mode: None) -> None:
    res = client.post("/sessions", json={})
    assert res.status_code == 401
    assert res.headers["www-authenticate"] == "Bearer"
    # 공개 정보는 로그인 없이
    assert client.get("/health").status_code == 200
    assert client.get("/opening-questions").status_code == 200


def test_neon_mode_valid_token_and_ownership(client: TestClient, neon_mode: None) -> None:
    sid = client.post("/sessions", json={}, headers=bearer(token("alice"))).json()["id"]
    assert client.get(f"/sessions/{sid}", headers=bearer(token("alice"))).status_code == 200
    assert client.get(f"/sessions/{sid}", headers=bearer(token("bob"))).status_code == 404


def test_neon_mode_ignores_spoofed_header(client: TestClient, neon_mode: None) -> None:
    sid = client.post("/sessions", json={}, headers=bearer(token("alice"))).json()["id"]
    res = client.get(f"/sessions/{sid}", headers={"X-User-Id": "alice"})
    assert res.status_code == 401


@pytest.mark.parametrize(
    "bad",
    [
        token(key=OTHER_KEY),  # 다른 키로 서명
        token(exp_in=-3600),  # 만료
        token(iss="https://evil.example.com"),  # 다른 발급자
        token(aud="https://other-app.example.com"),  # 다른 대상
        "not-a-jwt",
    ],
    ids=["wrong-key", "expired", "wrong-issuer", "wrong-audience", "garbage"],
)
def test_neon_mode_rejects_bad_tokens(client: TestClient, neon_mode: None, bad: str) -> None:
    res = client.post("/sessions", json={}, headers=bearer(bad))
    assert res.status_code == 401
    assert "로그인" in res.json()["detail"]


def test_banned_user_is_forbidden(client: TestClient, neon_mode: None) -> None:
    res = client.post("/sessions", json={}, headers=bearer(token(banned=True)))
    assert res.status_code == 403
