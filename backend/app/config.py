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


@lru_cache
def get_settings() -> Settings:
    return Settings()
