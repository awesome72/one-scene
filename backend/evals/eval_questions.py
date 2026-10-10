"""질문 품질 평가 (docs/claude-code-guide.md 12장 Phase 8, 기획안 10장 지표).

golden 시나리오(tests/golden/scenarios.yaml)를 실제 파이프라인에 넣고,
코치 응답과 재료 추출을 지표로 잰다. 실제 API를 부르므로 비용이 든다 (1회 약 1~2달러).

    cd backend && PYTHONUTF8=1 uv run python -m evals.eval_questions [--only quit,dog] [--label 메모]

결과: experiments/eval/<시각>.md (표) + .json (원자료)
"""

import argparse
import asyncio
import json
import math
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from app.config import REPO_DIR, get_settings
from app.db import Base, make_engine
from app.engine import reviewer
from app.engine.extractor import find_verbatim
from app.engine.llm import AnthropicLLM
from app.engine.pipeline import handle_user_turn
from app.models import Turn, User, WritingSession

HERE = Path(__file__).resolve().parent
SCENARIOS = HERE.parent / "tests" / "golden" / "scenarios.yaml"
OUT_DIR = REPO_DIR / "experiments" / "eval"

# 기획안 10장 목표
TARGETS = {
    "single_question": 0.98,
    "follows_user": 0.85,
    "first_pass": 0.80,
}
# $/1M 토큰 (claude-api 스킬 기준, 2026-09). 캐시 쓰기는 입력의 1.25배
PRICES = {
    "claude-sonnet-5-5": {"in": 2.0, "out": 10.0, "cache_read": 0.20},
    "claude-haiku-4-5-20251001": {"in": 1.0, "out": 5.0, "cache_read": 0.10},
    "claude-haiku-4-5": {"in": 1.0, "out": 5.0, "cache_read": 0.10},
    "claude-opus-5-5": {"in": 4.0, "out": 20.0, "cache_read": 0.20},
}
QUOTED = re.compile(r"[‘'\"“]([^‘'\"“”’]{2,60})[’'\"”]")


class Judgement(BaseModel):
    generic: bool
    follows_user: bool
    single_question: bool
    concrete: bool
    no_interpretation: bool
    respects_skip: bool
    reason: str


def cost(usage: list[dict[str, Any]]) -> float:
    total = 0.0
    for u in usage:
        p = PRICES.get(u["model"])
        if not p:
            continue
        total += (
            u["input"] * p["in"]
            + u["cache_write"] * p["in"] * 1.25
            + u["cache_read"] * p["cache_read"]
            + u["output"] * p["out"]
        ) / 1_000_000
    return total


def quotes_in(text: str) -> list[str]:
    return [m.group(1).strip() for m in QUOTED.finditer(text)]


async def run_scenario(factory: sessionmaker, llm: AnthropicLLM, sc: dict) -> dict[str, Any]:
    with factory() as db:
        if db.get(User, "eval") is None:
            db.add(User(id="eval"))
            db.commit()
        session = WritingSession(user_id="eval")
        session.turns.append(Turn(idx=0, role="coach", text=sc["opening_question"], stage=1))
        db.add(session)
        db.commit()
        turns = []
        for answer in sc["answers"]:
            started = time.perf_counter()
            events, first_delta, question_at = [], None, None
            async for e in handle_user_turn(db, llm, session, answer, "text"):
                events.append(e)
                now = time.perf_counter() - started
                if e["event"] == "question_delta" and first_delta is None:
                    first_delta = now
                if e["event"] == "question":
                    question_at = now
            elapsed = time.perf_counter() - started
            kinds = [e["event"] for e in events]
            materials = next((e["data"]["added"] for e in events if e["event"] == "materials"), [])
            question = next((e["data"]["turn"] for e in events if e["event"] == "question"), None)
            coach = session.turns[-1] if question else None
            turns.append({
                "user": answer,
                "prev_question": session.turns[-3].text if question else session.turns[-2].text,
                "coach": question["text"] if question else None,
                "meta": coach.meta if coach else None,
                "materials": materials,
                "events": kinds,
                "seconds": round(elapsed, 1),
                "first_delta_seconds": round(first_delta, 2) if first_delta is not None else None,
                "question_seconds": round(question_at, 2) if question_at is not None else None,
            })
        signals = [{"kind": s.kind, "value": s.value, "count": s.count} for s in session.signals]
        return {"id": sc["id"], "name": sc["name"], "tags": sc.get("tags", []), "turns": turns,
                "signals": signals, "topic": session.topic_sentence,
                "length": session.target_length}


async def judge(llm: AnthropicLLM, model: str, t: dict) -> Judgement:
    user = (
        f"<코치의 직전 질문>\n{t['prev_question']}\n</코치의 직전 질문>\n\n"
        f"<사용자의 마지막 말>\n{t['user']}\n</사용자의 마지막 말>\n\n"
        f"<채점할 코치 응답>\n{t['coach']}\n</채점할 코치 응답>"
    )
    return await llm.parse(model=model, system=(HERE / "judge.md").read_text("utf-8"),
                           user=user, schema=Judgement, max_tokens=2000)


def rate(values: list[bool]) -> float:
    return sum(values) / len(values) if values else float("nan")


def analyse(results: list[dict]) -> dict[str, Any]:
    coach_turns = [t for r in results for t in r["turns"]
                   if t["coach"] and not (t["meta"] or {}).get("fixed")]
    all_user_turns = [t for r in results for t in r["turns"]]
    m: dict[str, Any] = {}
    m["coach_turns"] = len(coach_turns)
    m["single_question"] = rate([reviewer.rule_check(t["coach"]) == [] or
                                 t["coach"].count("?") == 1 for t in coach_turns])
    m["single_question_rule"] = rate([t["coach"].count("?") + t["coach"].count("？") == 1
                                      for t in coach_turns])
    # 검수 1차 통과 = 실시간 규칙 검사 첫 시도 통과 + 보낸 뒤 LLM 검수 통과
    m["first_pass"] = rate([
        t["meta"]["attempts"][0]["passed"] and t["meta"].get("review", {}).get("passed", True)
        for t in coach_turns
    ])
    m["llm_review_pass"] = rate([
        t["meta"]["review"]["passed"] for t in coach_turns if "review" in t["meta"]
    ])
    m["final_passed"] = rate([t["meta"]["passed"] for t in coach_turns])
    m["avg_attempts"] = sum(len(t["meta"]["attempts"]) for t in coach_turns) / len(coach_turns)
    js = [t["judge"] for t in coach_turns]
    for key in ("follows_user", "single_question", "concrete", "no_interpretation",
                "respects_skip"):
        m[f"judge_{key}"] = rate([j[key] for j in js])
    m["judge_generic"] = rate([j["generic"] for j in js])
    # F3: 코치가 인용한 말이 사용자 원문 그대로인가
    quote_checks = []
    for r in results:
        said: list[str] = []
        for t in r["turns"]:
            said.append(t["user"])  # 앞선 발화를 다시 인용하는 것도 원문이면 통과
            if t in coach_turns:
                for q in quotes_in(t["coach"]):
                    quote_checks.append(any(find_verbatim(q, u) for u in said))
    m["quote_verbatim"] = rate(quote_checks)
    m["quote_count"] = len(quote_checks)
    # F1: 사용자가 따옴표로 말한 대사가 dialogue 재료로 잡혔는가
    dialogue_checks = []
    for t in all_user_turns:
        for q in quotes_in(t["user"]):
            dialogue_checks.append(any(
                m_["type"] == "dialogue" and (q in m_["text"] or m_["text"].strip('"“” ') in q)
                for m_ in t["materials"]))
    m["dialogue_captured"] = rate(dialogue_checks)
    m["dialogue_count"] = len(dialogue_checks)
    mats = [x for t in all_user_turns for x in t["materials"]]
    m["materials"] = len(mats)
    m["arc_assigned"] = rate([x["arc_block"] is not None for x in mats])
    m["avg_seconds"] = sum(t["seconds"] for t in all_user_turns) / len(all_user_turns)
    q_secs = [t["question_seconds"] for t in all_user_turns if t.get("question_seconds")]
    d_secs = [t["first_delta_seconds"] for t in all_user_turns if t.get("first_delta_seconds")]
    m["avg_question_seconds"] = sum(q_secs) / len(q_secs) if q_secs else float("nan")
    m["avg_first_delta_seconds"] = sum(d_secs) / len(d_secs) if d_secs else float("nan")
    return m


def report(results: list[dict], m: dict, spent: float, label: str) -> str:
    def pct(x: float) -> str:
        return "—" if math.isnan(x) else f"{x * 100:.0f}%"

    def mark(x: float, target: float) -> str:
        return "✅" if x >= target else "❌"

    lines = [
        f"# 질문 품질 평가 {datetime.now().astimezone():%Y-%m-%d %H:%M}" + (f" — {label}" if label else ""),
        "",
        (f"시나리오 {len(results)}개, 코치 응답 {m['coach_turns']}개, 비용 약 ${spent:.2f}, "
         f"첫 글자 {m['avg_first_delta_seconds']:.1f}초 · 질문 완성 {m['avg_question_seconds']:.1f}초 "
         f"· 턴 전체 {m['avg_seconds']:.1f}초"),
        "",
        "## 기획안 10장 지표",
        "| 지표 | 결과 | 목표 | |",
        "|---|---|---|---|",
        (f"| 응답당 질문 수 = 1 (규칙) | {pct(m['single_question_rule'])} | 98% | "
         f"{mark(m['single_question_rule'], TARGETS['single_question'])} |"),
        (f"| 직전 발화 이어받기 (독립 채점) | {pct(m['judge_follows_user'])} | 85% | "
         f"{mark(m['judge_follows_user'], TARGETS['follows_user'])} |"),
        (f"| 질문 검수 1차 통과 | {pct(m['first_pass'])} | 80% | "
         f"{mark(m['first_pass'], TARGETS['first_pass'])} |"),
        "",
        "## 그 밖의 지표",
        "| 지표 | 결과 | 설명 |",
        "|---|---|---|",
        f"| **어느 대답 뒤에 붙여도 되는 질문** | {pct(m['judge_generic'])} | 핵심 개선 지표, 낮을수록 좋음 |",
        f"| 장면을 묻는 질문 | {pct(m['judge_concrete'])} | 철칙 2 |",
        f"| 해석·요약·조언 없음 (F5) | {pct(m['judge_no_interpretation'])} | 철칙 3 |",
        f"| 넘어간 이야기 다시 안 묻기 | {pct(m['judge_respects_skip'])} | 8장 |",
        f"| 채점자 기준 질문 하나 | {pct(m['judge_single_question'])} | 철칙 1 |",
        f"| 검수 최종 통과 (규칙) | {pct(m['final_passed'])} | 3회 안에 통과 |",
        f"| 보낸 뒤 LLM 검수 통과 | {pct(m['llm_review_pass'])} | 기록용 |",
        f"| 평균 생성 횟수 | {m['avg_attempts']:.2f} | 1이면 재생성 없음 |",
        f"| 코치 인용이 원문 그대로 (F3) | {pct(m['quote_verbatim'])} | 인용 {m['quote_count']}개 |",
        f"| 따옴표 대사 → dialogue 재료 (F1) | {pct(m['dialogue_captured'])} | 대사 {m['dialogue_count']}개 |",
        f"| 아크 블록 배정 | {pct(m['arc_assigned'])} | 재료 {m['materials']}개 |",
        "",
        "## 문제가 된 응답",
    ]
    for r in results:
        for i, t in enumerate(r["turns"], 1):
            j = t.get("judge")
            if not j:
                continue
            bad = [k for k in ("follows_user", "single_question", "concrete", "no_interpretation",
                               "respects_skip") if not j[k]]
            if j["generic"]:
                bad.insert(0, "generic")
            if bad:
                lines.append(f"- **{r['name']} {i}턴** [{', '.join(bad)}] {t['coach']}  \n"
                             f"  ↳ 사용자: {t['user'][:60]}…  \n  ↳ {j['reason']}")
    lines += ["", "## 시나리오별 주제·길이 추출 (F2)"]
    lines += [f"- {r['name']}: 주제 {r['topic']!r}, 길이 {r['length']}" for r in results]
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="쉼표로 구분한 시나리오 id")
    ap.add_argument("--label", default="", help="결과에 남길 메모 (예: '기준선', 'F5 수정 후')")
    ap.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args()

    scenarios = yaml.safe_load(SCENARIOS.read_text("utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in wanted]

    tmp = tempfile.mkdtemp()
    engine = make_engine(f"sqlite:///{tmp}/eval.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    llm = AnthropicLLM()
    # 평가는 사후 LLM 검수를 표본이 아니라 매번 돌린다 (검수 1차 통과 지표)
    get_settings().review_sample_rate = 1.0
    judge_model = get_settings().model_fidelity  # 고품질 모델로 독립 채점

    sem = asyncio.Semaphore(args.concurrency)

    async def guarded(sc: dict) -> dict:
        async with sem:
            print(f"  ▸ {sc['name']}", flush=True)
            return await run_scenario(factory, llm, sc)

    print(f"시나리오 {len(scenarios)}개 실행 중…", flush=True)
    results = await asyncio.gather(*(guarded(s) for s in scenarios))

    print("채점 중…", flush=True)
    to_judge = [t for r in results for t in r["turns"]
                if t["coach"] and not (t["meta"] or {}).get("fixed")]
    judgements = await asyncio.gather(*(judge(llm, judge_model, t) for t in to_judge))
    for t, j in zip(to_judge, judgements, strict=True):
        t["judge"] = j.model_dump()

    metrics = analyse(results)
    spent = cost(llm.usage)
    md = report(results, metrics, spent, args.label)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = f"{datetime.now().astimezone():%Y%m%d-%H%M}"
    (OUT_DIR / f"{stamp}.md").write_text(md, encoding="utf-8")
    (OUT_DIR / f"{stamp}.json").write_text(
        json.dumps({"label": args.label, "metrics": metrics, "cost_usd": spent,
                    "results": results}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(md)
    print(f"\n저장: experiments/eval/{stamp}.md")


if __name__ == "__main__":
    asyncio.run(main())
