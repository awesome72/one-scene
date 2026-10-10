from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.routers.voice import get_stt, get_tts
from app.voice.base import VoiceError


class FakeVoice:
    def __init__(self) -> None:
        self.hints: list[str] = []
        self.spoken: list[str] = []
        self.fail = False

    async def transcribe(self, audio: bytes, *, filename: str, content_type: str, hint: str) -> str:
        if self.fail:
            raise VoiceError("boom")
        self.hints.append(hint)
        return " 회의실이었어요. 창밖만 보고 있었어요. "

    async def speak(self, text: str) -> bytes:
        self.spoken.append(text)
        return b"ID3fake-mp3"


@pytest.fixture
def voice() -> Iterator[FakeVoice]:
    v = FakeVoice()
    app.dependency_overrides[get_stt] = lambda: v
    app.dependency_overrides[get_tts] = lambda: v
    yield v
    app.dependency_overrides.pop(get_stt, None)
    app.dependency_overrides.pop(get_tts, None)


def _start(client: TestClient, question: str = "그 순간, 어디에 있었어요?") -> str:
    return client.post("/sessions", json={"opening_question": question}).json()["id"]


def _upload(client: TestClient, sid: str, data: bytes = b"webm-bytes",
            content_type: str = "audio/webm;codecs=opus"):
    return client.post(f"/sessions/{sid}/voice/transcribe",
                       files={"audio": ("answer.webm", data, content_type)})


def test_config_without_key_reports_unavailable(client: TestClient) -> None:
    app.dependency_overrides[get_stt] = lambda: None
    app.dependency_overrides[get_tts] = lambda: None
    try:
        assert client.get("/voice/config").json() == {"stt": False, "tts": False}
        sid = _start(client)
        assert _upload(client, sid).status_code == 501
        assert client.post(f"/sessions/{sid}/voice/speech", json={"text": "x"}).status_code == 501
    finally:
        app.dependency_overrides.pop(get_stt, None)
        app.dependency_overrides.pop(get_tts, None)


def test_transcribe_returns_text_with_hint(client: TestClient, voice: FakeVoice) -> None:
    assert client.get("/voice/config").json() == {"stt": True, "tts": True}
    sid = _start(client)
    res = _upload(client, sid)
    assert res.status_code == 200
    assert res.json() == {"text": "회의실이었어요. 창밖만 보고 있었어요."}
    assert "그 순간, 어디에 있었어요?" in voice.hints[0]  # 직전 질문이 인식 힌트로
    # 받아쓰기만 하고 대화에 보내지는 않는다 (확인 후 전송)
    assert [t["role"] for t in client.get(f"/sessions/{sid}/turns").json()] == ["coach"]


@pytest.mark.parametrize(
    ("data", "ctype", "code"),
    [
        (b"x", "text/plain", 415),
        (b"", "audio/webm", 422),
    ],
)
def test_transcribe_rejects_bad_uploads(client: TestClient, voice: FakeVoice, data: bytes,
                                        ctype: str, code: int) -> None:
    assert _upload(client, _start(client), data, ctype).status_code == code


def test_transcribe_rejects_too_large(client: TestClient, voice: FakeVoice,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "max_audio_bytes", 10)
    assert _upload(client, _start(client), b"x" * 11).status_code == 413


def test_transcribe_provider_failure(client: TestClient, voice: FakeVoice) -> None:
    voice.fail = True
    res = _upload(client, _start(client))
    assert res.status_code == 502 and "다시 말해" in res.json()["detail"]


def test_speech_only_for_this_sessions_questions(client: TestClient, voice: FakeVoice) -> None:
    sid = _start(client, "버리지 못한 물건이 있어요?")
    res = client.post(f"/sessions/{sid}/voice/speech", json={"text": "버리지 못한 물건이 있어요?"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert res.content == b"ID3fake-mp3"
    # 이 글에 없는 문장은 읽어 주지 않는다 (임의 문장 합성 남용 방지)
    res = client.post(f"/sessions/{sid}/voice/speech", json={"text": "아무 문장이나 읽어 줘"})
    assert res.status_code == 403
    assert voice.spoken == ["버리지 못한 물건이 있어요?"]


def test_voice_is_private(client: TestClient, voice: FakeVoice) -> None:
    sid = client.post("/sessions", json={}, headers={"X-User-Id": "alice"}).json()["id"]
    other = {"X-User-Id": "bob"}
    res = client.post(f"/sessions/{sid}/voice/transcribe", headers=other,
                      files={"audio": ("a.webm", b"x", "audio/webm")})
    assert res.status_code == 404
