"""DB 마이그레이션 (Alembic, app/migrate.py)."""

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from app import migrate
from app.db import Base, make_engine


def _diff(engine) -> list:
    with engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn), Base.metadata)


def _head() -> str:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(migrate._config()).get_current_head()


def _version(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def test_fresh_db_matches_models(tmp_path: Path) -> None:
    """빈 DB에 마이그레이션을 적용하면 모델과 똑같다. 모델을 바꾸고 마이그레이션을 안 만들면 여기서 걸린다."""
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    migrate.upgrade(engine)
    assert _diff(engine) == []
    assert _version(engine) == _head()


def test_create_all_db_is_stamped_without_changes(tmp_path: Path) -> None:
    """create_all로 만든 예전 DB(운영): 표를 건드리지 않고 기준선으로 표시한 뒤 올린다. 두 번 돌려도 같다."""
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, created_at) VALUES ('u1', CURRENT_TIMESTAMP)"))
    migrate.upgrade(engine)
    migrate.upgrade(engine)
    assert "alembic_version" in inspect(engine).get_table_names() and _version(engine) == _head()
    assert _diff(engine) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 1  # 데이터는 그대로
