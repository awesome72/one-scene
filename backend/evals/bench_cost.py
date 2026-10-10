"""턴당 API 호출 수와 비용 측정 (평가 채점 호출은 빼고 서비스 파이프라인만).

시나리오 두 개의 답을 이어 붙여 한 글을 길게 쓰는 것처럼 돌린다 (대화가 길수록 캐시 효과가 드러난다).

    cd backend && PYTHONUTF8=1 uv run python -m evals.bench_cost [--turns 8]
"""

import argparse
import asyncio
import tempfile
from collections import defaultdict

import yaml
from sqlalchemy.orm import sessionmaker

from app.db import Base, make_engine
from app.engine import metering
from app.engine.llm import AnthropicLLM
from app.engine.pipeline import handle_user_turn
from app.models import Turn, User, WritingSession
from evals.eval_questions import SCENARIOS


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--turns", type=int, default=8)
    args = ap.parse_args()
    scenarios = {s["id"]: s for s in yaml.safe_load(SCENARIOS.read_text("utf-8"))}
    answers = (scenarios["quit"]["answers"] + scenarios["first_salary"]["answers"])[: args.turns]

    engine = make_engine(f"sqlite:///{tempfile.mkdtemp()}/b.db")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(User(id="bench"))
    session = WritingSession(user_id="bench")
    session.turns.append(Turn(idx=0, role="coach", text=scenarios["quit"]["opening_question"],
                              stage=1))
    db.add(session)
    db.commit()

    llm = AnthropicLLM()
    for answer in answers:
        async for _ in handle_user_turn(db, llm, session, answer, "text"):
            pass

    by_model: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for u in llm.usage:
        m = by_model[u["model"]]
        m["calls"] += 1
        m["cost"] += metering.cost(u)
        for k in ("input", "cache_read", "cache_write", "output"):
            m[k] += u[k]
    n = len(answers)
    total = sum(m["cost"] for m in by_model.values())
    calls = sum(m["calls"] for m in by_model.values())
    print(f"턴 {n}개 · 호출 {calls}회 (턴당 {calls / n:.2f}) · 비용 ${total:.4f} (턴당 ${total / n:.4f})")
    for model, m in by_model.items():
        print(f"  {model:28} 호출 {int(m['calls']):3} · ${m['cost']:.4f} · 입력 {int(m['input']):6}"
              f" 캐시읽기 {int(m['cache_read']):6} 캐시쓰기 {int(m['cache_write']):6} 출력 {int(m['output']):5}")


if __name__ == "__main__":
    asyncio.run(main())
