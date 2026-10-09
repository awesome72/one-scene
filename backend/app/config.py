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

    database_url: str = f"sqlite:///{BACKEND_DIR / 'one_scene.db'}"

    stt_provider: str = ""
    stt_api_key: str = ""
    voice_keep_original: bool = False

    # 로그인 없이 공개 배포하는 동안 API 비용을 지키는 하루 전체 AI 작업 상한 (0이면 끔)
    daily_llm_limit: int = 300

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
