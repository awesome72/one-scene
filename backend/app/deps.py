from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from app.db import DbDep
from app.models import User, WritingSession

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
