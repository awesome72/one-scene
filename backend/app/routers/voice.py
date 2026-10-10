"""말로 답하기(받아쓰기)·읽어 주기 (Phase 5). 업체 키가 없으면 501 — 프론트가 브라우저 음성으로 대비한다."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import DbDep
from app.deps import CurrentUserDep, OwnedSessionDep, VoiceQuotaDep, record_usage
from app.models import WritingSession
from app.voice.base import SpeechToText, TextToSpeech, VoiceError

router = APIRouter(tags=["voice"])

HINT_CHARS = 800


def get_stt() -> SpeechToText | None:
    if not get_settings().openai_api_key:
        return None
    from app.voice.openai_voice import OpenAIVoice

    return OpenAIVoice()


def get_tts() -> TextToSpeech | None:
    return get_stt()  # type: ignore[return-value]  # 같은 업체가 둘 다 맡는다


SttDep = Annotated[SpeechToText | None, Depends(get_stt)]
TtsDep = Annotated[TextToSpeech | None, Depends(get_tts)]


class VoiceConfig(BaseModel):
    stt: bool
    tts: bool


class Transcript(BaseModel):
    text: str


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=600)


def _unavailable() -> HTTPException:
    return HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "서버 음성을 쓸 수 없어요.")


def recognition_hint(session: WritingSession) -> str:
    """받아쓰기 힌트: 직전 질문, 주제, 반복된 말, 최근 재료 (기획안: 고유명사 사용자 사전)."""
    question = next((t.text for t in reversed(session.turns) if t.role == "coach"), "")
    repeated = [s.value for s in session.signals if s.kind == "repeated"]
    recent = [m.text for m in session.materials[-12:] if not m.excluded]
    parts = [question, session.topic_sentence or "", " ".join(repeated), " ".join(recent)]
    return " ".join(p for p in parts if p)[:HINT_CHARS]


def speakable_texts(session: WritingSession) -> set[str]:
    """읽어 줄 수 있는 글: 이 글의 코치 질문과 최신 초안의 교정 질문뿐 (임의 문장 합성 남용 방지)."""
    texts = {t.text for t in session.turns if t.role == "coach"}
    if session.drafts:
        texts |= {h["question"] for h in session.drafts[-1].lint_result or []}
    return texts


@router.get("/voice/config")
def voice_config(_: CurrentUserDep, stt: SttDep, tts: TtsDep) -> VoiceConfig:
    return VoiceConfig(stt=stt is not None, tts=tts is not None)


@router.post("/sessions/{session_id}/voice/transcribe", dependencies=[VoiceQuotaDep])
async def transcribe(
    session: OwnedSessionDep,
    stt: SttDep,
    audio: Annotated[UploadFile, File()],
    db: DbDep,
    user: CurrentUserDep,
) -> Transcript:
    """녹음 → 글. 자동 전송하지 않는다 — 사용자가 확인·수정한 뒤 /turns로 보낸다. 녹음은 저장하지 않는다."""
    if stt is None:
        raise _unavailable()
    content_type = (audio.content_type or "").split(";")[0]
    if not content_type.startswith(("audio/", "video/webm")):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "녹음 파일이 아니에요.")
    limit = get_settings().max_audio_bytes
    data = await audio.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, "녹음이 너무 길어요. 나눠서 말해 주세요."
        )
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "녹음이 비어 있어요.")
    record_usage(db, user, "stt")
    try:
        text = await stt.transcribe(
            data,
            filename=audio.filename or "answer.webm",
            content_type=content_type,
            hint=recognition_hint(session),
        )
    except VoiceError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "잘 받아 적지 못했어요. 다시 말해 주세요."
        ) from None
    return Transcript(text=text.strip())


@router.post("/sessions/{session_id}/voice/speech", dependencies=[VoiceQuotaDep])
async def speech(
    body: SpeechRequest, session: OwnedSessionDep, tts: TtsDep, db: DbDep, user: CurrentUserDep
) -> Response:
    """코치 질문·교정 질문 → mp3."""
    if tts is None:
        raise _unavailable()
    if body.text not in speakable_texts(session):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "이 글의 질문만 읽어 줄 수 있어요.")
    record_usage(db, user, "tts")
    try:
        audio = await tts.speak(body.text)
    except VoiceError:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "읽어 주지 못했어요.") from None
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=86400"},
    )
