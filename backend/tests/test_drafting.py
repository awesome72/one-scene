from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.engine import cliche_linter, fidelity, outline, stage_machine
from app.engine.assembler import AssembledDraft, DraftParagraph, DraftSentence
from app.engine.drafting import FilledBlank, FilledSentence
from app.engine.extractor import ExtractedMaterial, Extraction
from app.engine.fidelity import FidelityResult, SentenceVerdict
from app.engine.llm import get_llm
from app.main import app
from app.models import Material, Signal, Turn, WritingSession
from tests.fakes import FakeLLM
from tests.test_turns import parse_sse

CLICHES = yaml.safe_load(
    (Path(cliche_linter.__file__).parent.parent / "data" / "cliches.yaml").read_text("utf-8")
)

# ---------- 린터 ----------


@pytest.mark.parametrize(
    ("kind", "entry"),
    [(k, e) for k in ("emotion_name", "cliche", "exaggeration") for e in CLICHES[k]],
    ids=lambda v: v if isinstance(v, str) else v["pattern"][:15],
)
def test_linter_detects_every_dictionary_example(kind: str, entry: dict) -> None:
    for example in entry["examples"]:
        hits = cliche_linter.lint_sentences([example])
        assert any(h.label == entry["label"] for h in hits), (example, hits)
        assert all("{match}" not in h.question for h in hits)  # C1: 자리표시자가 채워진다


def test_linter_question_quotes_the_match() -> None:
    [hit] = cliche_linter.lint_sentences(["가슴이 먹먹했다."])
    assert hit.question.startswith("'가슴이 먹먹'")
    assert (hit.start, hit.end) == (0, 6)


@pytest.mark.parametrize(
    "last",
    ["그날 나는 버티는 게 내 일이 아니라는 것을 깨달았다.", "앞으로는 그 자리에서 바로 말해야 한다"],
)
def test_linter_catches_moral_ending(last: str) -> None:
    hits = cliche_linter.lint_sentences(["회의실 창밖으로 주차장이 보였다.", last])
    assert any(h.kind == "moral_ending" and h.sentence == 1 for h in hits)


def test_moral_ending_checks_last_real_sentence_not_blank() -> None:
    hits = cliche_linter.lint_sentences(
        ["나는 그때 깨달았다.", "[빈칸: 그 뒤에 무엇을 했어요?]"], [False, True]
    )
    assert any(h.kind == "moral_ending" and h.sentence == 0 for h in hits)
    assert any(h.kind == "blank" and h.question == "그 뒤에 무엇을 했어요?" for h in hits)


def test_linter_no_overlap_and_long_sentence() -> None:
    hits = cliche_linter.lint_sentences(["모든 것이 달라졌다."])
    assert [h.label for h in hits] == ["깨달음 상투"]  # '모든' 과장으로 또 잡지 않는다
    long = "가" * 61 + "."
    assert any(h.kind == "long_sentence" for h in cliche_linter.lint_sentences([long]))


def test_mockup_draft_marks() -> None:
    """목업 초안 화면의 표시 4곳이 모두 잡힌다 (design-spec.md ⑥)."""
    sentences = [
        "그날 회의실 창밖으로 주차장이 보였다.",
        "가슴이 먹먹했다.",
        "나는 너무 지쳐 있었다.",
        "[빈칸: 그때 손은 무엇을 하고 있었나요?]",
        "그때는 몰랐다, 그 회의가 마지막이 될 줄.",
    ]
    hits = cliche_linter.lint_sentences(sentences, [False, False, False, True, False])
    assert {h.label for h in hits} >= {"상투 표현", "과장", "재료가 없는 자리", "깨달음 상투"}


# ---------- 개요 ----------


def _session(materials: list[tuple[str, str]], length: str = "medium") -> WritingSession:
    s = WritingSession(user_id="u", stage=3, target_length=length)
    s.turns.append(Turn(id="t", idx=0, role="user", text="x", stage=3))
    for i, (block, text) in enumerate(materials, 1):
        s.materials.append(Material(id=f"id{i}", seq=i, turn_id="t", text=text, type="scene",
                                    arc_block=block, excluded=False))
    return s


@pytest.mark.parametrize("pattern", list(outline.PATTERNS))
def test_outline_patterns_start_and_end_right(pattern: str) -> None:
    s = _session([("scene", "a"), ("scene", "b"), ("event", "c"), ("meaning", "d"),
                  ("present", "e"), ("present", "f"), ("resonance", "g")])
    items = outline.plan(s, pattern)  # type: ignore[arg-type]
    assert items[-1].arc_block == "resonance"
    assert sum(i.target_chars for i in items) == pytest.approx(2500, abs=100)
    used = {m.id for i in items for m in i.materials}
    assert used == {f"id{n}" for n in range(1, 8)}  # 재료가 빠짐없이 들어간다


def test_return_pattern_splits_scene_materials() -> None:
    s = _session([("scene", "회의실"), ("scene", "아 이건 아니다"), ("resonance", "하늘")])
    items = outline.plan(s, "return")
    assert [i.label for i in items][:3] == ["장면", "사건과 배경", "장면으로 돌아오기"]
    assert [m.text for m in items[0].materials] == ["회의실"]
    assert [m.text for m in items[2].materials] == ["아 이건 아니다"]


# ---------- 진실성 ----------


def _materials() -> list[Material]:
    return [
        Material(id="a", seq=1, turn_id="t", text="회의실 창밖만 보고 있었어요", type="scene",
                 arc_block="scene", excluded=False),
        Material(id="b", seq=2, turn_id="t", text="이번 분기만 버티자", type="dialogue",
                 arc_block="event", excluded=False),
    ]


def test_structural_check_blanks_unsourced_sentences() -> None:
    draft = AssembledDraft(paragraphs=[DraftParagraph(outline_position=1, sentences=[
        DraftSentence(text="나는 회의실 창밖만 보고 있었다.", material_ids=["m1"]),
        DraftSentence(text="그날은 비가 내렸다.", material_ids=[]),  # 출처 없음
        DraftSentence(text="팀장은 웃었다.", material_ids=["m9"]),  # 없는 재료
        DraftSentence(text="그때 손은?", is_blank=True),
    ])])
    out = fidelity.structural(draft, _materials())
    assert [s.is_blank for s in out] == [False, True, True, True]
    assert out[0].material_ids == ["a"]
    assert out[3].text == "[빈칸: 그때 손은?]"
    assert "비가 내렸다" not in " ".join(s.text for s in out)


@pytest.mark.asyncio
async def test_semantic_check_blanks_invented_weather() -> None:
    """가이드 Phase 6 테스트 (1): 재료에 없는 날씨를 넣은 가짜 초안이 걸린다."""
    llm = FakeLLM()
    llm.queue(FidelityResult(verdicts=[
        SentenceVerdict(index=0, ok=False, added="비", question="그날 창밖은 어땠어요?"),
        SentenceVerdict(index=1, ok=True),
    ]))
    draft = AssembledDraft(paragraphs=[DraftParagraph(outline_position=1, sentences=[
        DraftSentence(text="비 내리는 창밖만 보고 있었다.", material_ids=["m1"]),
        DraftSentence(text="팀장은 '이번 분기만 버티자'고 했다.", material_ids=["m2"]),
    ])])
    out = await fidelity.check(llm, draft, _materials())
    assert out[0].is_blank and out[0].text == "[빈칸: 그날 창밖은 어땠어요?]"
    assert "비 내리는" in out[0].note
    assert not out[1].is_blank
    sent = llm.parse_calls[0]["user"]
    assert "회의실 창밖만 보고 있었어요" in sent  # 출처 재료 원문을 함께 보낸다


# ---------- API ----------


@pytest.fixture
def fake() -> Iterator[FakeLLM]:
    llm = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    yield llm
    app.dependency_overrides.pop(get_llm, None)


def _seed(db: Session, client: TestClient) -> str:
    sid = client.post("/sessions", json={}).json()["id"]
    s = db.get(WritingSession, sid)
    s.stage = 3
    s.target_length = "short"
    turn = s.turns[0]
    for i, (block, text) in enumerate(
        [("scene", "회의실 창밖만 보고 있었어요"), ("event", "이번 분기만 버티자"),
         ("meaning", "버티는 게 내 일이 아니라는 생각"), ("present", "그 자리에서 바로 말해요"),
         ("resonance", "창밖을 봤는데 그냥 하늘이 보였어요")], 1):
        s.materials.append(Material(seq=i, turn_id=turn.id, text=text, type="scene",
                                    arc_block=block))
    s.signals.append(Signal(kind="repeated", value="창밖", count=2))
    db.commit()
    return sid


def test_outline_preview_and_save(client: TestClient, db_session: Session, fake: FakeLLM) -> None:
    sid = _seed(db_session, client)
    preview = client.get(f"/sessions/{sid}/outline", params={"pattern": "return"}).json()
    assert preview["saved"] is False
    assert [i["label"] for i in preview["items"]][2] == "장면으로 돌아오기"
    assert preview["bookends"] == ["창밖"]
    assert len(preview["patterns"]) == 4

    saved = client.post(f"/sessions/{sid}/outline", json={"pattern": "linear"}).json()
    assert saved["saved"] is True and saved["pattern"] == "linear"
    assert stage_machine.is_ready_to_close(db_session.get(WritingSession, sid))
    assert client.get(f"/sessions/{sid}/outline").json()["pattern"] == "linear"


def test_draft_requires_outline(client: TestClient, db_session: Session, fake: FakeLLM) -> None:
    sid = _seed(db_session, client)
    events = parse_sse(client.post(f"/sessions/{sid}/drafts").text)
    assert events[-1][0] == "error"


def test_draft_flow_dismiss_and_answer(
    client: TestClient, db_session: Session, fake: FakeLLM
) -> None:
    sid = _seed(db_session, client)
    client.post(f"/sessions/{sid}/outline", json={"pattern": "linear"})
    fake.queue(AssembledDraft(paragraphs=[
        DraftParagraph(outline_position=1, sentences=[
            DraftSentence(text="나는 회의실 창밖만 보고 있었다.", material_ids=["m1"]),
            DraftSentence(text="가슴이 먹먹했다.", material_ids=["m1"]),
        ]),
        DraftParagraph(outline_position=2, sentences=[
            DraftSentence(text="그때 손은 무엇을 하고 있었나요?", is_blank=True),
        ]),
        DraftParagraph(outline_position=5, sentences=[
            DraftSentence(text="창밖을 봤다. 그냥 하늘이 보였다.", material_ids=["m5"]),
        ]),
    ]))
    fake.queue(FidelityResult(verdicts=[SentenceVerdict(index=i, ok=True) for i in (0, 1, 3)]))
    events = parse_sse(client.post(f"/sessions/{sid}/drafts").text)
    assert [k for k, _ in events] == ["status", "status", "draft"]
    draft = events[-1][1]["draft"]
    assert draft["version"] == 1 and draft["blank_count"] == 1
    assert [p["position"] for p in draft["paragraphs"]] == [1, 2, 5]
    assert draft["paragraphs"][0]["sentences"][0]["materials"][0]["text"] == "회의실 창밖만 보고 있었어요"
    kinds = {h["kind"]: h for h in draft["hits"]}
    assert set(kinds) == {"cliche", "blank"}

    # 그대로 두기
    res = client.post(f"/sessions/{sid}/drafts/{draft['id']}/hits/{kinds['cliche']['id']}/dismiss")
    assert res.json()["open_hits"] == 1

    # 빈칸 질문에 답하기 → 원문 재료가 되고, 대화 기록에 질문·답이 남고, 그 빈칸을 답의 재료로 바로 채운다
    fake.extractions.append(Extraction(materials=[
        ExtractedMaterial(text="볼펜 뚜껑을 열었다 닫았다", type="object", arc_block="event")
    ]))
    fake.queue(FilledBlank(sentences=[
        FilledSentence(text="나는 볼펜 뚜껑을 열었다 닫았다.", material_ids=["m6"]),
        FilledSentence(text="딸깍 소리가 났다.", material_ids=["m6"]),
    ]))
    fake.queue(FidelityResult(verdicts=[SentenceVerdict(index=0, ok=True),
                                        SentenceVerdict(index=1, ok=True)]))
    res = client.post(
        f"/sessions/{sid}/drafts/{draft['id']}/hits/{kinds['blank']['id']}/answer",
        json={"text": "볼펜 뚜껑을 열었다 닫았다 했어요"},
    ).json()
    assert [m["text"] for m in res["added"]] == ["볼펜 뚜껑을 열었다 닫았다"]
    filled = res["draft"]["paragraphs"][1]["sentences"]
    assert res["draft"]["blank_count"] == 0 and res["draft"]["version"] == 1
    # 두 문장이어도 빈칸 한 자리에: 뒤 문장 번호(교정 표시 id)가 바뀌지 않는다
    assert [s["text"] for s in filled] == ["나는 볼펜 뚜껑을 열었다 닫았다. 딸깍 소리가 났다."]
    assert filled[0]["index"] == 2 and res["draft"]["paragraphs"][2]["sentences"][0]["index"] == 3
    assert filled[0]["materials"][0]["text"] == "볼펜 뚜껑을 열었다 닫았다"
    assert res["draft"]["open_hits"] == 0
    # 채우기에는 새 재료와 앞뒤 문장만 간다
    fill_prompt = [c for c in fake.parse_calls if c["schema"] is FilledBlank][-1]["user"]
    assert "m6 (object): 볼펜 뚜껑을 열었다 닫았다" in fill_prompt and "앞 문장:" in fill_prompt
    turns = client.get(f"/sessions/{sid}/turns").json()
    assert [t["text"] for t in turns[-2:]] == [
        "그때 손은 무엇을 하고 있었나요?", "볼펜 뚜껑을 열었다 닫았다 했어요"
    ]
    assert client.get(f"/sessions/{sid}/drafts/latest").json()["id"] == draft["id"]


def test_redraft_keeps_dismissed_hits(
    client: TestClient, db_session: Session, fake: FakeLLM
) -> None:
    sid = _seed(db_session, client)
    client.post(f"/sessions/{sid}/outline", json={"pattern": "linear"})
    para = DraftParagraph(outline_position=1, sentences=[
        DraftSentence(text="가슴이 먹먹했다.", material_ids=["m1"])])
    for _ in range(2):
        fake.queue(AssembledDraft(paragraphs=[para]))
        fake.queue(FidelityResult(verdicts=[SentenceVerdict(index=0, ok=True)]))
    first = parse_sse(client.post(f"/sessions/{sid}/drafts").text)[-1][1]["draft"]
    client.post(f"/sessions/{sid}/drafts/{first['id']}/hits/{first['hits'][0]['id']}/dismiss")
    second = parse_sse(client.post(f"/sessions/{sid}/drafts").text)[-1][1]["draft"]
    assert second["version"] == 2
    assert second["hits"][0]["dismissed"] is True


def test_redraft_includes_materials_added_after_outline(
    client: TestClient, db_session: Session, fake: FakeLLM
) -> None:
    sid = _seed(db_session, client)
    client.post(f"/sessions/{sid}/outline", json={"pattern": "linear"})
    blank_para = DraftParagraph(outline_position=2, sentences=[
        DraftSentence(text="그 말은 어떤 문장이었나요?", is_blank=True)])
    fake.queue(AssembledDraft(paragraphs=[blank_para]))
    first = parse_sse(client.post(f"/sessions/{sid}/drafts").text)[-1][1]["draft"]
    hit = first["hits"][0]
    fake.extractions.append(Extraction(materials=[
        ExtractedMaterial(text="볼펜으로 화이트보드를 두드렸어요", type="scene", arc_block="event")
    ]))
    # 채울 문장을 못 쓰면(빈 결과) 빈칸은 그대로 두고 표시만 닫는다. 재료는 다시 만들 때 쓰인다
    fake.queue(FilledBlank(sentences=[]))
    res = client.post(f"/sessions/{sid}/drafts/{first['id']}/hits/{hit['id']}/answer",
                      json={"text": "팀장님은 볼펜으로 화이트보드를 두드렸어요"}).json()
    assert res["draft"]["blank_count"] == 1 and res["draft"]["open_hits"] == 0

    fake.queue(AssembledDraft(paragraphs=[blank_para]))
    client.post(f"/sessions/{sid}/drafts")
    assemble_prompt = [c for c in fake.parse_calls if c["schema"] is AssembledDraft][-1]["user"]
    assert "볼펜으로 화이트보드를 두드렸어요" in assemble_prompt


# ---------- 직접 고치기 ----------


def test_split_sentences_keeps_blanks_and_quotes() -> None:
    from app.engine.drafting import split_sentences

    text = '팀장은 "이번 분기만 버티자."라고 했다. 나는 창밖을 봤다.[빈칸: 그때 손은요?] 그냥 하늘이었다…'
    assert split_sentences(text) == [
        '팀장은 "이번 분기만 버티자."라고 했다.',
        "나는 창밖을 봤다.",
        "[빈칸: 그때 손은요?]",
        "그냥 하늘이었다…",
    ]


def test_edit_draft_keeps_sources_marks_user_sentences(
    client: TestClient, db_session: Session, fake: FakeLLM
) -> None:
    sid = _seed(db_session, client)
    client.post(f"/sessions/{sid}/outline", json={"pattern": "linear"})
    fake.queue(AssembledDraft(paragraphs=[
        DraftParagraph(outline_position=1, sentences=[
            DraftSentence(text="나는 회의실 창밖만 보고 있었다.", material_ids=["m1"]),
            DraftSentence(text="가슴이 먹먹했다.", material_ids=["m1"]),
        ]),
        DraftParagraph(outline_position=2, sentences=[
            DraftSentence(text="그때 손은 무엇을 하고 있었나요?", is_blank=True),
        ]),
    ]))
    fake.queue(FidelityResult(verdicts=[SentenceVerdict(index=i, ok=True) for i in (0, 1)]))
    first = parse_sse(client.post(f"/sessions/{sid}/drafts").text)[-1][1]["draft"]
    calls_before = len(fake.parse_calls)

    res = client.post(f"/sessions/{sid}/drafts/{first['id']}/edit", json={"paragraphs": [
        "나는 회의실 창밖만 보고 있었다. 볼펜 뚜껑을 계속 열었다 닫았다.",
        "[빈칸: 그때 손은 무엇을 하고 있었나요?]",
    ]})
    assert res.status_code == 200
    draft = res.json()
    assert draft["version"] == 2
    assert len(fake.parse_calls) == calls_before  # LLM을 부르지 않는다
    s = [x for p in draft["paragraphs"] for x in p["sentences"]]
    assert [x["text"] for x in s] == [
        "나는 회의실 창밖만 보고 있었다.", "볼펜 뚜껑을 계속 열었다 닫았다.",
        "[빈칸: 그때 손은 무엇을 하고 있었나요?]",
    ]
    assert s[0]["edited"] is False and s[0]["materials"][0]["text"] == "회의실 창밖만 보고 있었어요"
    assert s[1]["edited"] is True and s[1]["materials"] == []
    assert s[2]["is_blank"] is True
    # '가슴이 먹먹했다'를 지웠으니 그 표시도 사라지고, 빈칸 표시는 남는다
    assert {h["kind"] for h in draft["hits"]} == {"blank"}
    assert client.get(f"/sessions/{sid}/drafts/latest").json()["version"] == 2


def test_edit_draft_validation_and_ownership(
    client: TestClient, db_session: Session, fake: FakeLLM
) -> None:
    sid = _seed(db_session, client)
    client.post(f"/sessions/{sid}/outline", json={"pattern": "linear"})
    fake.queue(AssembledDraft(paragraphs=[DraftParagraph(outline_position=1, sentences=[
        DraftSentence(text="나는 회의실 창밖만 보고 있었다.", material_ids=["m1"])])]))
    fake.queue(FidelityResult(verdicts=[SentenceVerdict(index=0, ok=True)]))
    did = parse_sse(client.post(f"/sessions/{sid}/drafts").text)[-1][1]["draft"]["id"]
    assert client.post(f"/sessions/{sid}/drafts/{did}/edit", json={"paragraphs": []}).status_code == 422
    other = {"X-User-Id": "someone-else"}
    res = client.post(f"/sessions/{sid}/drafts/{did}/edit", json={"paragraphs": ["x."]}, headers=other)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_missing_fidelity_verdict_becomes_blank() -> None:
    """판정이 빠진 문장은 확인 못 한 문장 → 빈칸 (제품 규칙 2)."""
    llm = FakeLLM()
    llm.queue(FidelityResult(verdicts=[SentenceVerdict(index=0, ok=True)]))  # 1번 판정 누락
    draft = AssembledDraft(paragraphs=[DraftParagraph(outline_position=1, sentences=[
        DraftSentence(text="나는 회의실 창밖만 보고 있었다.", material_ids=["m1"]),
        DraftSentence(text="팀장은 웃으며 버티자고 했다.", material_ids=["m2"]),
    ])])
    out = await fidelity.check(llm, draft, _materials())
    assert [s.is_blank for s in out] == [False, True]
    assert "판정 누락" in out[1].note


# ---------- AI 제안 ----------


@pytest.mark.asyncio
async def test_failed_sentences_become_suggestions() -> None:
    llm = FakeLLM()
    llm.queue(FidelityResult(verdicts=[
        SentenceVerdict(index=0, ok=False, added="비", question="그날 창밖은 어땠어요?"),
    ]))
    draft = AssembledDraft(paragraphs=[DraftParagraph(outline_position=1, sentences=[
        DraftSentence(text="비 내리는 창밖만 보고 있었다.", material_ids=["m1"]),
        DraftSentence(text="그날 저녁은 어땠나요?", is_blank=True,
                      suggestion="퇴근길 버스 창에 이마를 대고 있었다."),
        DraftSentence(text="팀장은 웃었다.", material_ids=[]),  # 출처 없음
    ])])
    out = await fidelity.check(llm, draft, _materials())
    assert [s.is_blank for s in out] == [True, True, True]
    assert [s.suggestion for s in out] == [
        "비 내리는 창밖만 보고 있었다.",  # 지어낸 문장은 본문이 아니라 제안으로
        "퇴근길 버스 창에 이마를 대고 있었다.",  # 조립기의 제안
        "팀장은 웃었다.",
    ]


def _draft_with_suggestions(client: TestClient, db_session: Session, fake: FakeLLM) -> tuple[str, dict]:
    sid = _seed(db_session, client)
    client.post(f"/sessions/{sid}/outline", json={"pattern": "linear"})
    fake.queue(AssembledDraft(paragraphs=[
        DraftParagraph(outline_position=1, sentences=[
            DraftSentence(text="나는 회의실 창밖만 보고 있었다.", material_ids=["m1"]),
            DraftSentence(text="그때 손은 무엇을 하고 있었나요?", is_blank=True,
                          suggestion="나는 볼펜 뚜껑을 열었다 닫았다 했다."),
        ]),
        DraftParagraph(outline_position=5, sentences=[
            DraftSentence(text="그 뒤 창밖은 어땠나요?", is_blank=True,
                          suggestion="창밖에는 그냥 하늘이 있었다."),
        ]),
    ]))
    fake.queue(FidelityResult(verdicts=[SentenceVerdict(index=0, ok=True)]))
    draft = parse_sse(client.post(f"/sessions/{sid}/drafts").text)[-1][1]["draft"]
    return sid, draft


def test_draft_shows_suggestions(client: TestClient, db_session: Session, fake: FakeLLM) -> None:
    _, draft = _draft_with_suggestions(client, db_session, fake)
    assert draft["suggestion_count"] == 2 and draft["blank_count"] == 2
    blank = draft["paragraphs"][0]["sentences"][1]
    assert blank["is_blank"] and blank["suggestion"] == "나는 볼펜 뚜껑을 열었다 닫았다 했다."
    # 아직 받아들이지 않은 제안은 본문 글자 수에 들어가지 않는다
    assert draft["char_count"] == len("나는 회의실 창밖만 보고 있었다.")


def test_accept_one_edit_one_then_all(client: TestClient, db_session: Session, fake: FakeLLM) -> None:
    sid, draft = _draft_with_suggestions(client, db_session, fake)
    did = draft["id"]
    res = client.post(f"/sessions/{sid}/drafts/{did}/sentences/1/accept", json={}).json()
    s1 = res["paragraphs"][0]["sentences"][1]
    assert (s1["text"], s1["is_blank"], s1["accepted"]) == ("나는 볼펜 뚜껑을 열었다 닫았다 했다.", False, True)
    assert res["suggestion_count"] == 1 and res["version"] == 1  # 같은 버전 안에서 바뀐다
    assert all(h["sentence"] != 1 or h["kind"] != "blank" for h in res["hits"])

    res = client.post(f"/sessions/{sid}/drafts/{did}/sentences/2/accept",
                      json={"text": "창밖은 어둑했고 하늘만 보였다."}).json()
    assert res["paragraphs"][1]["sentences"][0]["text"] == "창밖은 어둑했고 하늘만 보였다."
    assert res["blank_count"] == 0

    # 받아들일 제안이 없으면 모두 받아들이기는 아무것도 바꾸지 않는다
    again = client.post(f"/sessions/{sid}/drafts/{did}/accept-all").json()
    assert again["blank_count"] == 0
    assert client.post(f"/sessions/{sid}/drafts/{did}/sentences/99/accept", json={}).status_code == 404


def test_accept_all(client: TestClient, db_session: Session, fake: FakeLLM) -> None:
    sid, draft = _draft_with_suggestions(client, db_session, fake)
    res = client.post(f"/sessions/{sid}/drafts/{draft['id']}/accept-all").json()
    assert res["blank_count"] == 0 and res["suggestion_count"] == 0
    texts = [s["text"] for p in res["paragraphs"] for s in p["sentences"]]
    assert texts == ["나는 회의실 창밖만 보고 있었다.", "나는 볼펜 뚜껑을 열었다 닫았다 했다.",
                     "창밖에는 그냥 하늘이 있었다."]
    # 받아들인 문장은 '받아들인 AI 제안'으로 표시된다 (출처 재료 없음)
    assert [s["accepted"] for p in res["paragraphs"] for s in p["sentences"]] == [False, True, True]
