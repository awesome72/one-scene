from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.db import DbDep
from app.deps import OwnedSessionDep
from app.engine.llm import LLM, get_llm
from app.engine.pipeline import handle_user_turn
from app.schemas import TurnCreate

router = APIRouter(prefix="/sessions/{session_id}", tags=["turns"])

LlmDep = Annotated[LLM, Depends(get_llm)]


@router.post("/turns", response_class=EventSourceResponse)
async def post_turn(
    body: TurnCreate, session: OwnedSessionDep, db: DbDep, llm: LlmDep
) -> AsyncIterable[ServerSentEvent]:
    """사용자 발화 전송 → 진행 상황과 코치 질문을 SSE로.

    이벤트: status(extracting|asking|reviewing) → materials → card(선택) → question | error
    """
    async for event in handle_user_turn(db, llm, session, body.text, body.input_mode):
        yield ServerSentEvent(event=event["event"], data=event["data"])
