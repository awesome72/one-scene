from collections.abc import Iterator
from typing import Annotated, Any

from fastapi import Depends
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str, **kwargs: Any) -> Engine:
    is_sqlite = url.startswith("sqlite")
    if is_sqlite:
        kwargs.setdefault("connect_args", {"check_same_thread": False})
    else:
        # 서버리스: 함수가 잠들었다 깨어나면 끊긴 연결을 걸러 낸다
        kwargs.setdefault("pool_pre_ping", True)
        kwargs.setdefault("pool_size", 2)
        kwargs.setdefault("max_overflow", 3)
    engine = create_engine(url, **kwargs)
    if is_sqlite:

        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn: Any, _record: Any) -> None:
            # SQLite는 외래 키 검사를 연결마다 직접 켜야 한다
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


engine = make_engine(get_settings().sqlalchemy_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


DbDep = Annotated[Session, Depends(get_db)]
