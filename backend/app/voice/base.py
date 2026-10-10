"""음성 어댑터 (Phase 5). 업체를 바꿀 때는 이 프로토콜의 구현만 새로 만든다."""

from typing import Protocol


class VoiceError(RuntimeError):
    pass


class SpeechToText(Protocol):
    async def transcribe(
        self, audio: bytes, *, filename: str, content_type: str, hint: str
    ) -> str:
        """녹음 → 받아쓴 글. hint는 고유명사·직전 질문 같은 인식 힌트."""
        ...


class TextToSpeech(Protocol):
    async def speak(self, text: str) -> bytes:
        """글 → mp3 바이트."""
        ...
