"""OpenAI 음성 인식(gpt-4o-transcribe)·합성(gpt-4o-mini-tts)."""

import openai

from app.config import get_settings
from app.engine import resources
from app.voice.base import VoiceError


class OpenAIVoice:
    def __init__(self, client: openai.AsyncOpenAI | None = None) -> None:
        settings = get_settings()
        self.settings = settings
        self.client = client or openai.AsyncOpenAI(api_key=settings.openai_api_key)

    async def transcribe(
        self, audio: bytes, *, filename: str, content_type: str, hint: str
    ) -> str:
        try:
            result = await self.client.audio.transcriptions.create(
                model=self.settings.model_stt,
                file=(filename, audio, content_type),
                language="ko",
                prompt=hint[:800] or openai.omit,
                response_format="text",
            )
        except openai.OpenAIError as exc:
            raise VoiceError(f"받아쓰기 실패: {exc.__class__.__name__}") from exc
        text = result if isinstance(result, str) else getattr(result, "text", "")
        return text.strip()

    async def speak(self, text: str) -> bytes:
        try:
            response = await self.client.audio.speech.create(
                model=self.settings.model_tts,
                voice=self.settings.tts_voice,
                input=text,
                instructions=resources.prompt("tts_voice"),
                response_format="mp3",
            )
        except openai.OpenAIError as exc:
            raise VoiceError(f"음성 합성 실패: {exc.__class__.__name__}") from exc
        return response.content
