import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    anthropic_api_key: str = ""
    model_questioner: str = ""
    model_assembler: str = ""
    model_fidelity: str = ""
    model_extractor: str = ""
    model_reviewer: str = ""

    # Vercel 함수는 /tmp에만 쓸 수 있다. DATABASE_URL(Neon)이 없을 때의 임시 대비일 뿐 데이터는 유지되지 않는다
    database_url: str = (
        "sqlite:////tmp/one_scene.db"
        if os.environ.get("VERCEL")
        else f"sqlite:///{BACKEND_DIR / 'one_scene.db'}"
    )

    # 음성 (Phase 5, open-questions D1: OpenAI). 키가 없으면 프론트가 브라우저 내장 음성으로 대비한다
    openai_api_key: str = ""
    # 비용: mini 받아쓰기는 절반 값. 한국어 받아쓰기는 확인 화면에서 사용자가 고칠 수 있다
    model_stt: str = "gpt-4o-mini-transcribe"
    model_tts: str = "gpt-4o-mini-tts"
    tts_voice: str = "marin"
    # 녹음 원본은 받아쓰기 뒤 버린다 (기획안 12장). 4.5MB는 Vercel 함수 요청 본문 한도
    max_audio_bytes: int = 4_000_000

    # Neon Auth 주소 (Vercel Marketplace 연결이 넣어 준다). 있으면 로그인 필수 (app/auth.py)
    neon_auth_base_url: str = ""

    # 로그인 없이 공개 배포하는 동안 API 비용을 지키는 하루 전체 AI 작업 상한 (0이면 끔)
    daily_llm_limit: int = 300
    # 한 사람의 하루 AI 작업 상한 (글 한 편 ≈ 40~70턴. 하루에 한 편을 다 못 끝내면 다음 날 이어 쓴다)
    daily_llm_limit_per_user: int = 60
    # 질문을 보낸 뒤 도는 LLM 검수(기록용)를 몇 %만 돌릴지. 평가 스크립트는 1.0으로 돌린다 (비용)
    review_sample_rate: float = 0.1
    # 받아쓰기·읽어 주기 하루 상한 (사용자당). 건당 약 $0.001이라 AI 상한과 따로 넉넉하게
    daily_voice_limit_per_user: int = 200

    @property
    def sqlalchemy_url(self) -> str:
        """Neon/Vercel이 주는 postgres:// 주소를 psycopg 3 드라이버 주소로 바꾼다."""
        url = self.database_url
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
