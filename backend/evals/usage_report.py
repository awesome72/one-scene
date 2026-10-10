"""운영 보고: LLM 비용(llm_usage, engine/metering.py)과 단계별 이탈(journey_events).

    cd backend && PYTHONUTF8=1 uv run python -m evals.usage_report [--days 7]

운영 DB를 보려면 DATABASE_URL에 Neon 주소를 넣고 돌린다 (vercel env pull로 받은 값).
"""

import argparse
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.db import engine
from app.models import JourneyEvent, LlmUsage, StoryFeedback


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    since = datetime.now(UTC) - timedelta(days=args.days)
    db = sessionmaker(bind=engine)()
    where = LlmUsage.created_at >= since

    total, calls = db.execute(
        select(func.coalesce(func.sum(LlmUsage.cost_usd), 0), func.count()).where(where)
    ).one()
    print(f"최근 {args.days}일: 호출 {calls}회 · ${total:.4f}")

    day = func.date(LlmUsage.created_at)
    print("\n날짜별")
    for d, c, n in db.execute(
        select(day, func.sum(LlmUsage.cost_usd), func.count()).where(where)
        .group_by(day).order_by(day)
    ):
        print(f"  {d}  ${c:.4f}  호출 {n}")

    print("\n작업·모델별")
    for kind, model, c, n, inp, out, cr in db.execute(
        select(LlmUsage.kind, LlmUsage.model, func.sum(LlmUsage.cost_usd), func.count(),
               func.sum(LlmUsage.input_tokens), func.sum(LlmUsage.output_tokens),
               func.sum(LlmUsage.cache_read_tokens))
        .where(where).group_by(LlmUsage.kind, LlmUsage.model)
        .order_by(func.sum(LlmUsage.cost_usd).desc())
    ):
        print(f"  {kind:8} {model:28} ${c:.4f}  호출 {n:4}  입력 {inp:8} 캐시읽기 {cr:8} 출력 {out:7}")

    turns = db.scalar(select(func.count(func.distinct(LlmUsage.session_id)))
                      .where(where, LlmUsage.kind == "turn")) or 0
    if turns:
        turn_cost = db.scalar(select(func.sum(LlmUsage.cost_usd))
                              .where(where, LlmUsage.kind == "turn")) or 0
        print(f"\n대화한 글 {turns}편 · 글당 대화 비용 평균 ${turn_cost / turns:.4f}")

    print("\n단계별 이탈 (이 기간에 시작한 글)")
    started = set(db.scalars(select(JourneyEvent.session_id).where(
        JourneyEvent.created_at >= since, JourneyEvent.kind == "start")))
    if started:
        events = db.execute(select(JourneyEvent.session_id, JourneyEvent.kind, JourneyEvent.stage)
                            .where(JourneyEvent.session_id.in_(started))).all()
        reached = {n: {sid for sid, kind, st in events if kind == "advance" and st >= n}
                   for n in (2, 3, 4)}
        finished = {sid for sid, kind, _ in events if kind == "finish"}
        n0 = len(started)
        print(f"  시작 {n0}편")
        for n, name in ((2, "2단계 도착 (1단계 마침)"), (3, "3단계 도착"), (4, "4단계 도착")):
            print(f"  {name:18} {len(reached[n]):4}편 ({len(reached[n]) / n0:.0%})")
        print(f"  완성                {len(finished):4}편 ({len(finished) / n0:.0%})")
        if reached[2]:
            rate = len(finished & reached[2]) / len(reached[2])
            print(f"  1단계 마친 뒤 완성률 {rate:.0%} (기획안 목표 35%)")
    else:
        print("  기록 없음")

    avg, n = db.execute(select(func.avg(StoryFeedback.score), func.count())
                        .where(StoryFeedback.created_at >= since)).one()
    if n:
        print(f"\n'내 이야기 같다' 평균 {avg:.2f} / 5 ({n}편, 기획안 목표 4.3)")

    print("\n비용 상위 사용자")
    for user, c in db.execute(
        select(LlmUsage.user_id, func.sum(LlmUsage.cost_usd)).where(where)
        .group_by(LlmUsage.user_id).order_by(func.sum(LlmUsage.cost_usd).desc()).limit(5)
    ):
        print(f"  {user[:12]}…  ${c:.4f}")


if __name__ == "__main__":
    main()
