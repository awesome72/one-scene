"""기획안 10장 성공 지표 계산 (LLM 없이 저장된 기록으로).

- 글 품질: 출처 연결률 100%, 1,000자당 상투어 0.5개 이하, 첫 문장이 장면 90% 이상
- 사용자 행동: 첫 세션 → 1단계 완료 60%, 월 2편 이상 완성 20%, 음성 입력 40%
  (1단계 → 완성 35%와 만족도 4.3은 evals/usage_report.py가 따로 센다)
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Draft, JourneyEvent, Material, Turn, WritingSession

# 상투어 사전(data/cliches.yaml)의 세 갈래. 완성 글에 남아 있으면 '그대로 두기'했어도 센다
DICTIONARY_KINDS = ("cliche", "exaggeration", "emotion_name")
# 사용자가 확인한 문장: 직접 고침, 받아들인 AI 제안, 빈칸 답으로 채움 (제품 규칙 2)
CONFIRMED_SOURCES = ("user", "accepted", "filled")

TARGETS = {
    "source_rate": 1.0,
    "cliches_per_1000": 0.5,
    "first_scene_rate": 0.9,
    "first_session_stage1_rate": 0.6,
    "two_pieces_month_rate": 0.2,
    "voice_rate": 0.4,
}


@dataclass
class DraftQuality:
    sentences: int  # 빈칸이 아닌 문장
    sourced: int  # 재료에 연결됐거나 사용자가 확인한 문장
    chars: int
    dictionary_hits: int
    first_is_scene: bool | None  # 첫 문장의 출처가 장면 블록인가 (출처가 없으면 판단 안 함)

    @property
    def source_rate(self) -> float:
        return self.sourced / self.sentences if self.sentences else 1.0

    @property
    def cliches_per_1000(self) -> float:
        return self.dictionary_hits / self.chars * 1000 if self.chars else 0.0


def draft_quality(draft: Draft, materials: dict[str, Material]) -> DraftQuality:
    body = [s for s in draft.sentence_map if not s["is_blank"]]
    sourced = sum(
        1 for s in body
        if any(i in materials for i in s.get("material_ids") or [])
        or s.get("source") in CONFIRMED_SOURCES
    )
    first_is_scene = None
    if body:
        blocks = {materials[i].arc_block for i in body[0].get("material_ids") or [] if i in materials}
        first_is_scene = ("scene" in blocks) if blocks else None
    hits = sum(1 for h in draft.lint_result or [] if h.get("kind") in DICTIONARY_KINDS)
    return DraftQuality(len(body), sourced, sum(len(s["text"]) for s in body), hits, first_is_scene)


def finished_quality(db: Session, since: datetime) -> list[DraftQuality]:
    """이 기간에 완성한 글의 마지막 초안 품질."""
    finished = set(db.scalars(select(JourneyEvent.session_id).where(
        JourneyEvent.kind == "finish", JourneyEvent.created_at >= since)))
    out = []
    for sid in finished:
        session = db.get(WritingSession, sid)
        if session is None or not session.drafts:
            continue
        materials = {m.id: m for m in session.materials}
        out.append(draft_quality(session.drafts[-1], materials))
    return out


def behaviour(db: Session, since: datetime) -> dict[str, tuple[int, int]]:
    """(분자, 분모) 쌍. 비율은 보고하는 쪽이 나눈다 (표본이 작을 때 숫자를 함께 보이게)."""
    events = db.execute(select(JourneyEvent.user_id, JourneyEvent.session_id, JourneyEvent.kind,
                               JourneyEvent.stage, JourneyEvent.created_at)).all()
    by_user: dict[str, list] = defaultdict(list)
    for e in events:
        by_user[e.user_id].append(e)

    # 첫 세션 → 1단계 완료: 사용자의 첫 글(가장 이른 start)이 이 기간에 시작됐고 2단계로 넘어갔는가
    first_total = first_done = 0
    for evs in by_user.values():
        starts = sorted((e for e in evs if e.kind == "start"), key=lambda e: e.created_at)
        if not starts or _naive(starts[0].created_at) < _naive(since):
            continue
        first_total += 1
        sid = starts[0].session_id
        if any(e.session_id == sid and e.kind == "advance" and e.stage >= 2 for e in evs):
            first_done += 1

    # 월 2편 이상 완성: 이 기간에 활동한(글을 시작하거나 완성한) 사용자 중 완성 2편 이상
    active = {u for u, evs in by_user.items() if any(_naive(e.created_at) >= _naive(since) for e in evs)}
    two = sum(
        1 for u in active
        if len({e.session_id for e in by_user[u]
                if e.kind == "finish" and _naive(e.created_at) >= _naive(since)}) >= 2
    )

    # 음성 입력: 이 기간 사용자 발화 중 말로 한 것
    modes = db.scalars(select(Turn.input_mode).where(
        Turn.role == "user", Turn.created_at >= since)).all()
    return {
        "first_session_stage1_rate": (first_done, first_total),
        "two_pieces_month_rate": (two, len(active)),
        "voice_rate": (sum(1 for m in modes if m == "voice"), len(modes)),
    }


def _naive(t: datetime) -> datetime:
    # SQLite는 시간대를 잃는다. 비교는 UTC 기준 naive로
    return t.replace(tzinfo=None) if t.tzinfo else t
