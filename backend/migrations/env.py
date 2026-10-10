"""Alembic 환경: app.models의 메타데이터와 app.config의 DB 주소를 쓴다.

app/migrate.py가 연결을 config.attributes["connection"]으로 넘기면 그 연결을 쓰고,
CLI(alembic revision --autogenerate 등)로 부르면 설정의 DATABASE_URL로 연결한다.
"""

from alembic import context

from app import models  # noqa: F401  테이블 등록
from app.config import get_settings
from app.db import Base, make_engine

target_metadata = Base.metadata


def run() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = make_engine(get_settings().sqlalchemy_url)
    with engine.connect() as conn:
        _run(conn)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite는 ALTER가 약하다
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run()
