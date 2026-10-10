from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  테이블 등록
from app.db import Base, engine
from app.routers import drafts, library, sessions, turns, voice


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # 개발 단계: 테이블 자동 생성. PostgreSQL 전환 전에 Alembic 마이그레이션으로 바꾼다
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="한 장면 API", version="0.1.0", lifespan=lifespan)
app.include_router(sessions.router)
app.include_router(turns.router)
app.include_router(drafts.router)
app.include_router(library.router)
app.include_router(voice.router)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
