"""글 한 편 전체 시뮬레이션: 기억을 가진 가상의 사용자(Haiku)가 주제 설정부터 교정까지 실제 파이프라인으로 쓴다.

질문 품질 평가(eval_questions)가 '한 턴'을 본다면, 이것은 '여정'의 마찰을 잰다:
단계마다 몇 번 대답했는지(기획안 범위 대비), 마감 조건이 언제 찼는지, 초안의 빈칸·AI 제안 비율,
교정 답이 다음 초안에 반영되는지, 턴당 시간과 비용.

    cd backend && PYTHONUTF8=1 uv run python -m evals.simulate_journey [--only quit] [--max-turns 24]

결과: experiments/journey/<시각>.md (지표 + 대화 전문) — 내용은 모두 가상의 기억이다.
"""

import argparse
import asyncio
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.config import REPO_DIR, get_settings
from app.db import Base, make_engine
from app.engine import drafting, metering, progress
from app.engine.llm import AnthropicLLM
from app.engine.pipeline import handle_stage_open, handle_user_turn
from app.models import Turn, User, WritingSession

HERE = Path(__file__).resolve().parent
OUT_DIR = REPO_DIR / "experiments" / "journey"

PERSONAS: dict[str, dict[str, str]] = {
    "quit": {
        "name": "지현 (38세, 퇴사)",
        "length": "medium",
        "opening": "최근, 별일 아닌데 자꾸 생각나는 순간이 있어요?",
        "memory": """\
- 작년 11월, 7년 다닌 광고회사를 그만뒀다. 결정한 순간은 화요일 오전 주간 회의 때였다.
- 회의실은 12층, 창가 자리. 창밖으로 회사 주차장과 내 회색 아반떼가 보였다.
- 팀장은 3년째 "이번 분기만 버티자"라는 말을 했다. 처음 들은 건 입사 4년 차 겨울 워크숍, 양평 펜션.
- 그날 회의에서 팀장이 또 그 말을 하자 '아 이건 아니다' 싶었다. 손에 쥔 볼펜 뚜껑을 계속 딸깍거렸다.
- 그 주 금요일 사직서를 냈다. 팀장은 "생각 좀 더 해 봐"라고만 했다.
- 마지막 출근 날 책상에서 머그컵(남편이 준 파란 컵) 하나만 챙겼다.
- 지금은 작은 출판사에서 일한다. 회의에서 할 말이 있으면 그 자리에서 바로 말한다. 지난주에도 일정이 무리라고 바로 말했다.
- 요즘도 회의실에 들어가면 창가 자리를 피한다. 창밖을 보면 그날 생각이 나서.
- 그 결정이 무엇이었는지: 버티는 게 내 일이 아니라는 걸 처음 인정한 날. (이 말은 코치가 의미를 물을 때만, 조금 망설이다 꺼낸다)""",
    },
    "kitchen": {
        "name": "영수 (63세, 할머니의 부엌)",
        "length": "short",
        "opening": "버리지 못하고 아직 갖고 있는 물건이 있어요?",
        "memory": """\
- 할머니가 쓰던 양은 냄비를 아직 갖고 있다. 손잡이 한쪽이 찌그러져 있다. 지금은 베란다 선반 위에 있다.
- 어릴 때(1970년대, 경북 영주) 방학마다 할머니 집에 갔다. 부엌은 흙바닥이고 아궁이가 두 개였다.
- 할머니는 그 냄비에 늘 감자를 쪘다. 소금을 한 꼬집 넣고 "다 익었다, 뜨거우니 호호 불어라" 했다.
- 부엌에서는 늘 장작 타는 냄새와 된장 냄새가 났다. 문틈으로 겨울바람이 들어왔다.
- 손잡이가 찌그러진 건 내가 아홉 살 때 냄비를 떨어뜨려서다. 할머니는 혼내지 않고 "냄비도 나이를 먹는 거다" 했다.
- 할머니는 내가 스물두 살 때(1983년) 돌아가셨다. 장례 뒤에 어머니가 그 냄비를 내게 줬다.
- 지금은 가끔 손주들이 오면 그 냄비에 감자를 찐다. 소금 한 꼬집. "호호 불어라"라고 나도 모르게 말한다.
- 감정은 잘 말하지 못한다. "그립죠 뭐" 정도로 짧게 말하는 편이다.""",
    },
}


async def persona_answer(llm: AnthropicLLM, memory: str, transcript: list[tuple[str, str]]) -> str:
    convo = "\n".join(f"{'코치' if r == 'coach' else '나'}: {t}" for r, t in transcript[-10:])
    system = (HERE / "persona.md").read_text("utf-8").format(memory=memory)
    return await llm.text(
        model=get_settings().model_extractor,  # 가상 사용자는 Haiku로 (비용)
        system=[{"type": "text", "text": system}],
        messages=[{"role": "user", "content": f"지금까지의 대화:\n{convo}\n\n코치의 마지막 질문에 답하세요."}],
        max_tokens=400,
    )


async def run_events(gen: Any) -> list[dict]:
    return [e async for e in gen]


async def simulate(
    factory: sessionmaker, llm: AnthropicLLM, user_llm: AnthropicLLM, key: str, max_turns: int
) -> dict[str, Any]:
    p = PERSONAS[key]
    db = factory()
    db.add(User(id=f"sim-{key}"))
    session = WritingSession(user_id=f"sim-{key}")
    session.turns.append(Turn(idx=0, role="coach", text=p["opening"], stage=1))
    db.add(session)
    db.commit()
    transcript: list[tuple[str, str]] = [("coach", p["opening"])]
    stages: list[dict[str, Any]] = []
    seconds: list[float] = []
    card_at: dict[int, int] = {}
    phases: dict[str, float] = {}  # 서비스 비용만 (가상 사용자 비용은 user_llm에 따로)

    def mark(name: str, start: int) -> int:
        phases[name] = phases.get(name, 0.0) + sum(metering.cost(u) for u in llm.usage[start:])
        return len(llm.usage)

    at = len(llm.usage)
    for stage in (1, 2):
        turns_here = 0
        ready_at = None
        while turns_here < max_turns:
            answer = (await persona_answer(user_llm, p["memory"], transcript)).strip()
            transcript.append(("user", answer))
            t0 = time.perf_counter()
            events = await run_events(handle_user_turn(db, llm, session, answer, "voice"))
            seconds.append(time.perf_counter() - t0)
            turns_here += 1
            q = next((e["data"]["turn"]["text"] for e in events if e["event"] == "question"), None)
            if any(e["event"] == "card" for e in events):
                card_at.setdefault(stage, turns_here)
                choose_on_card(session, p)
                db.commit()
            if q:
                transcript.append(("coach", q))
            pr = progress.build(session)
            if pr.ready and ready_at is None:
                ready_at = turns_here
                break  # 사용자는 조건이 차면 넘어간다고 가정 (가장 빠른 경로)
        pr = progress.build(session)
        stages.append({
            "stage": stage, "turns": turns_here, "ready_at": ready_at, "card_at": card_at.get(stage),
            "expected": progress.EXPECTED_TURNS[stage],
            "missing": [c.label for c in pr.conditions if not c.done],
        })
        if ready_at is None:
            break  # 마감 조건을 못 채우면 거기서 멈춘다 (이탈 지점)
        session.stage += 1
        db.commit()
        events = await run_events(handle_stage_open(db, llm, session))
        q = next((e["data"]["turn"]["text"] for e in events if e["event"] == "question"), None)
        if q:
            transcript.append(("coach", f"[{session.stage}단계 시작] {q}"))

    at = mark("대화(1~2단계)", at)
    draft_info: dict[str, Any] = {}
    if session.stage >= 3:
        outline = drafting.outline_view(session)
        pattern = outline.pattern or "linear"
        drafting.save_outline(db, session, pattern)
        session.stage = 4
        db.commit()
        first = await make_draft(db, llm, session)
        at = mark("초안 조립·검사", at)
        # 빈칸 교정 질문 셋에 가상 사용자가 답한 뒤 다시 만든다
        answered = 0
        while answered < 3:
            draft = session.drafts[-1]
            # 화면처럼 매번 지금 초안의 열린 빈칸 표시를 다시 읽는다
            hit = next((h for h in draft.lint_result or [] if h["kind"] == "blank" and not h.get("dismissed")), None)
            if hit is None:
                break
            transcript.append(("coach", f"[교정] {hit['question']}"))
            answer = (await persona_answer(user_llm, p["memory"], transcript)).strip()
            transcript.append(("user", answer))
            await drafting.answer_hit(db, llm, session, draft, hit["id"], answer, "voice")
            answered += 1
        at = mark("빈칸 답·채우기", at)
        # 빈칸에 답하면 그 자리가 바로 채워진다 (다시 만들지 않은 지금 초안)
        now = drafting.draft_out(session.drafts[-1], session).model_dump(mode="json")
        after = summarize(now, 0.0)
        draft_info = {"pattern": pattern, "first": first, "second": after, "answered": answered}

    return {"key": key, "name": p["name"], "stages": stages, "seconds": seconds, "phases": phases,
            "transcript": transcript, "draft": draft_info,
            "materials": len([m for m in session.materials if not m.excluded])}


def choose_on_card(session: WritingSession, persona: dict[str, str]) -> None:
    """재료 카드에서 사용자가 하는 일: 내 말 한 문장을 주제로, 길이를 고른다 (MaterialCard.tsx와 같은 후보 규칙)."""
    if not session.topic_sentence:
        choices = sorted(
            {m.text for m in session.materials if not m.excluded and len(m.text) >= 8
             and (m.type == "interpretation" or m.arc_block == "meaning")},
            key=len, reverse=True,
        )
        fallback = sorted((m.text for m in session.materials if m.arc_block == "scene"), key=len)
        session.topic_sentence = (choices or fallback[-1:] or [None])[0]
    if not session.target_length:
        session.target_length = persona.get("length", "medium")


async def make_draft(db: Any, llm: AnthropicLLM, session: WritingSession) -> dict[str, Any]:
    t0 = time.perf_counter()
    events = await run_events(drafting.handle_draft(db, llm, session))
    out = next((e["data"]["draft"] for e in events if e["event"] == "draft"), None)
    if out is None:
        return {"error": [e for e in events if e["event"] == "error"], "seconds": time.perf_counter() - t0}
    return summarize(out, time.perf_counter() - t0)


def summarize(out: dict[str, Any], seconds: float) -> dict[str, Any]:
    sentences = [s for p in out["paragraphs"] for s in p["sentences"]]
    return {
        "seconds": round(seconds, 1),
        "sentences": len(sentences),
        "own": sum(1 for s in sentences if not s["is_blank"]),
        "blanks": sum(1 for s in sentences if s["is_blank"]),
        "suggestions": sum(1 for s in sentences if s["is_blank"] and s.get("suggestion")),
        "hits": out["hits"],
        "chars": out["char_count"],
        "body": "\n\n".join(
            " ".join(("[빈칸]" if s["is_blank"] else s["text"]) for s in p["sentences"])
            for p in out["paragraphs"]
        ),
    }


def report(results: list[dict], spent: float) -> str:
    lines = [f"# 여정 시뮬레이션 {datetime.now().astimezone():%Y-%m-%d %H:%M}", "",
             f"비용 약 ${spent:.2f} (가상 사용자 포함)", ""]
    for r in results:
        lines += [f"## {r['name']}", "", "| 단계 | 대답 | 카드 | 조건 충족 | 기획안 범위 | 남은 조건 |", "|---|---|---|---|---|---|"]
        for s in r["stages"]:
            lo, hi = s["expected"]
            lines.append(f"| {s['stage']} | {s['turns']} | {s['card_at'] or '-'} | {s['ready_at'] or '못 채움'} | {lo}~{hi} | {', '.join(s['missing']) or '-'} |")
        secs = sorted(r["seconds"])
        if secs:
            lines.append(f"\n턴 시간 중앙값 {secs[len(secs) // 2]:.1f}초 · 최대 {secs[-1]:.1f}초 · 재료 {r['materials']}개")
        if r.get("phases"):
            total = sum(r["phases"].values())
            lines.append("\n서비스 비용 (가상 사용자 제외): " + " · ".join(
                f"{k} ${v:.3f}" for k, v in r["phases"].items()) + f" · 합계 ${total:.3f}")
        d = r["draft"]
        if d:
            for label, k in (("첫 초안", "first"), ("빈칸 답 뒤 (다시 만들지 않음)", "second")):
                x = d[k]
                if "error" in x:
                    lines.append(f"\n{label}: 오류 {x['error']}")
                    continue
                lines.append(f"\n**{label}** ({d['pattern']}, {x['seconds']}초): 문장 {x['sentences']} · 내 말 {x['own']} · "
                             f"빈칸 {x['blanks']} (AI 제안 {x['suggestions']}) · {x['chars']}자")
                lines.append("\n> " + x["body"].replace("\n\n", "\n>\n> "))
            lines.append(f"\n교정 답 {d['answered']}개")
        lines += ["", "<details><summary>대화 전문</summary>", ""]
        lines += [f"- **{'코치' if role == 'coach' else '나'}**: {text}" for role, text in r["transcript"]]
        lines += ["", "</details>", ""]
    return "\n".join(lines)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="쉼표로 구분한 페르소나 (quit, kitchen)")
    ap.add_argument("--max-turns", type=int, default=24, help="한 단계에서 넘어가지 못하고 멈추는 대답 수")
    args = ap.parse_args()
    keys = [k for k in PERSONAS if not args.only or k in args.only.split(",")]
    engine = make_engine(f"sqlite:///{tempfile.mkdtemp()}/journey.db")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    # 페르소나마다 서비스 LLM을 따로 둔다: 동시에 돌 때 단계별 비용이 섞이지 않게
    llms = {k: AnthropicLLM() for k in keys}
    user_llm = AnthropicLLM()  # 가상 사용자 호출은 서비스 비용과 따로 센다
    get_settings().review_sample_rate = 0.0  # 사후 검수는 여정 측정과 무관 (비용)
    results = await asyncio.gather(*(simulate(factory, llms[k], user_llm, k, args.max_turns) for k in keys))
    spent = sum(metering.cost(u) for x in [*llms.values(), user_llm] for u in x.usage)
    md = report(list(results), spent)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{datetime.now().astimezone():%Y%m%d-%H%M}.md"
    path.write_text(md, encoding="utf-8")
    print(md.split("<details>")[0])
    for r in results:
        for s in r["stages"]:
            print(r["key"], s)
    print(f"\n저장: {path.relative_to(REPO_DIR)}")


if __name__ == "__main__":
    asyncio.run(main())
