from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.db import DbDep
from app.deps import LlmQuotaDep, OwnedSessionDep
from app.engine.llm import LLM, get_llm
from app.engine.pipeline import Event, handle_stage_open, handle_user_turn
from app.schemas import TurnCreate

router = APIRouter(prefix="/sessions/{session_id}", tags=["turns"])

LlmDep = Annotated[LLM, Depends(get_llm)]


def _sse(event: Event) -> ServerSentEvent:
    return ServerSentEvent(event=event["event"], data=event["data"])


@router.post("/turns", response_class=EventSourceResponse, dependencies=[LlmQuotaDep])
async def post_turn(
    body: TurnCreate, session: OwnedSessionDep, db: DbDep, llm: LlmDep
) -> AsyncIterable[ServerSentEvent]:
    """사용자 발화 전송 → 진행 상황과 코치 질문을 SSE로.

    이벤트: status(extracting|asking|reviewing) → materials → card(선택) → question | error
    """
    async for event in handle_user_turn(
        db, llm, session, body.text, body.input_mode, skip=body.skip
    ):
        yield _sse(event)


@router.post("/coach", response_class=EventSourceResponse, dependencies=[LlmQuotaDep])
async def post_coach(
    session: OwnedSessionDep, db: DbDep, llm: LlmDep
) -> AsyncIterable[ServerSentEvent]:
    """사용자 발화 없이 코치 질문 하나 (단계를 넘기거나 되돌린 뒤의 여는 질문).

    이벤트: status(asking|reviewing) → question | error
    """
    async for event in handle_stage_open(db, llm, session):
        yield _sse(event)
