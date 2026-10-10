import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import (
    migrate,
    models,  # noqa: F401  테이블 등록
)
from app.db import engine
from app.engine.llm import UNAVAILABLE_MESSAGE, LLMError, LLMUnavailable
from app.routers import drafts, library, sessions, turns, voice


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # DB 스키마를 최신으로 (Alembic, app/migrate.py). create_all 시절 DB는 기준선으로 표시한다
    migrate.upgrade(engine)
    yield


log = logging.getLogger(__name__)

app = FastAPI(title="한 장면 API", version="0.1.0", lifespan=lifespan)
app.include_router(sessions.router)
app.include_router(turns.router)
app.include_router(drafts.router)
app.include_router(library.router)
app.include_router(voice.router)


@app.exception_handler(LLMError)
async def llm_error(_: Request, exc: LLMError) -> JSONResponse:
    """SSE가 아닌 AI 요청(태그 제안, 교정 답 등)이 실패했을 때: 500 대신 503과 정해 둔 문구."""
    log.error("LLM 요청 실패: %s", exc)
    message = (UNAVAILABLE_MESSAGE if isinstance(exc, LLMUnavailable)
               else "AI 요청을 처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.")
    return JSONResponse(status_code=503, content={"detail": message})


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}
