from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import func, select

from app.config import get_settings
from app.db import DbDep
from app.models import Draft, Turn, User, WritingSession

DEV_USER_ID = "dev-user"


def get_current_user(
    db: DbDep,
    x_user_id: Annotated[str | None, Header(max_length=64)] = None,
) -> User:
    """임시 인증: X-User-Id 헤더로 사용자를 구분한다 (open-questions B2).

    베타 전에 실제 인증(매직링크 등)으로 바꾼다. 헤더가 없으면 개발용 사용자.
    """
    user_id = x_user_id or DEV_USER_ID
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        db.add(user)
        db.commit()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_owned_session(session_id: str, db: DbDep, user: CurrentUserDep) -> WritingSession:
    session = db.get(WritingSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "세션을 찾을 수 없습니다.")
    return session


OwnedSessionDep = Annotated[WritingSession, Depends(get_owned_session)]


def require_llm_quota(db: DbDep) -> None:
    """하루 전체 AI 작업 상한 (config.daily_llm_limit). 로그인 없이 공개 배포하는 동안의 비용 안전장치.

    사용자 발화(추출+질문)와 초안 조립을 한 건씩 센다. UTC 자정에 초기화된다.
    """
    limit = get_settings().daily_llm_limit
    if limit <= 0:
        return
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = (
        db.scalar(select(func.count()).where(Turn.role == "user", Turn.created_at >= today)) or 0
    ) + (db.scalar(select(func.count()).where(Draft.created_at >= today)) or 0)
    if used >= limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "오늘 쓸 수 있는 양을 다 썼어요. 내일 다시 이어서 써 주세요.",
        )


LlmQuotaDep = Depends(require_llm_quota)
