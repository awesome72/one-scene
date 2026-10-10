from pathlib import Path

import pytest
import yaml

from app.engine import prompt_builder, reviewer, stage_machine
from app.engine.extractor import ExtractedMaterial, Extraction, find_verbatim, keep_verbatim
from app.models import Material, OutlineItem, Signal, Turn, WritingSession

GOLDEN = yaml.safe_load(
    (Path(__file__).parent / "golden" / "quit_job.yaml").read_text(encoding="utf-8")
)

# ---------- extractor: 원문 보존 ----------

UTTER = '회의실이었어요. 팀장님이 "이번 분기만   버티자"고 했어요. 창밖만 보고 있었어요.'


@pytest.mark.parametrize(
    ("fragment", "expected"),
    [
        ("창밖만 보고 있었어요", "창밖만 보고 있었어요"),
        ("이번 분기만 버티자", "이번 분기만   버티자"),  # 공백 차이 → 원문 표기로
        ("“이번 분기만 버티자”", '"이번 분기만   버티자"'),  # 굽은 따옴표 → 원문 표기로
        ("창밖으로 비가 내렸어요", None),  # 지어낸 문장
        ("회의실에서 창밖을 봤어요", None),  # 요약·재구성
        ("", None),
    ],
)
def test_find_verbatim(fragment: str, expected: str | None) -> None:
    assert find_verbatim(fragment, UTTER) == expected


def test_keep_verbatim_drops_fabrication() -> None:
    raw = Extraction(
        materials=[
            ExtractedMaterial(text="회의실이었어요", type="place", arc_block="scene"),
            ExtractedMaterial(text="비 내리는 회의실", type="sense", arc_block="scene"),
            ExtractedMaterial(text="회의실이었어요", type="place", arc_block="scene"),  # 중복
        ],
        key_words=["창밖", "날씨", "팀"],
        topic_sentence="퇴사는 용기에 관한 이야기",
    )
    kept = keep_verbatim(raw, UTTER)
    assert [m.text for m in kept.materials] == ["회의실이었어요"]
    assert kept.key_words == ["창밖"]  # 원문에 없는 '날씨', 한 글자 '팀' 제외
    assert kept.topic_sentence is None


# ---------- reviewer: 규칙 검사 ----------


@pytest.mark.parametrize("text", [t["text"] for t in GOLDEN["turns"] if t["role"] == "coach"])
def test_golden_coach_responses_pass_rules(text: str) -> None:
    assert reviewer.rule_check(text) == []


@pytest.mark.parametrize("bad", GOLDEN["bad"])
def test_golden_bad_response_fails_rules(bad: dict) -> None:
    reasons = reviewer.rule_check(bad["text"])
    assert any("물음표" in r for r in reasons)


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("멋진 이야기네요. 그때 어디에 있었어요?", "상투어"),
        ("많이 힘드셨겠어요. 그날 무엇을 했어요?", "상투어"),
        ("정리하면 결국 이건 용기 이야기네요. 다음은 뭐예요?", "요약"),
        ("그때 어디에 있었어요? 그리고 누구와 있었어요?", "물음표"),
        ("그때 어디에 있었어요? 누구와요.", "맨 끝"),
        ("회의실이요. 창밖이요. 하늘이요. 소리요. 그때 무엇을 들었어요?", "문장"),
        ("어디에 있었는지, 그리고 누구와 있었어요?", "잇고"),
    ],
)
def test_rule_violations(text: str, needle: str) -> None:
    reasons = reviewer.rule_check(text)
    assert any(needle in r for r in reasons), reasons


@pytest.mark.asyncio
async def test_reviewer_skips_llm_when_rules_fail() -> None:
    from tests.fakes import FakeLLM

    llm = FakeLLM()
    review = await reviewer.run(llm, question="좋은 질문이에요?", last_user_text="x", stage=1)
    assert not review.passed
    assert llm.parse_calls == []


@pytest.mark.asyncio
async def test_reviewer_recomputes_passed_from_checks() -> None:
    from tests.fakes import PASS, FakeLLM

    lying = PASS.model_copy(update={"not_leading": False, "passed": True})
    review = await reviewer.run(
        FakeLLM(reviews=[lying]), question="그때 외로우셨죠?", last_user_text="x", stage=1
    )
    assert not review.passed


# ---------- stage_machine ----------


def _session(stage: int = 1) -> WritingSession:
    s = WritingSession(user_id="u", stage=stage)
    s.turns.append(Turn(idx=0, role="user", text="t", stage=stage))
    return s


def _mat(seq: int, block: str, type_: str = "scene") -> Material:
    return Material(id=f"id{seq}", seq=seq, turn_id="t", text=f"재료{seq}", type=type_,
                    arc_block=block, excluded=False)


def test_stage1_needs_topic_scene_and_length() -> None:
    s = _session(1)
    assert set(stage_machine.missing(s)) == {"한 문장 주제", "오프닝 장면", "목표 길이"}
    s.topic_sentence = "그만둔 날"
    s.target_length = "medium"
    s.materials.append(_mat(1, "scene"))
    assert stage_machine.is_ready_to_close(s)


def test_stage2_needs_all_blocks_senses_and_own_meaning() -> None:
    s = _session(2)
    for i, block in enumerate(["scene", "event", "meaning", "present", "resonance"], 1):
        s.materials.append(_mat(i, block))
    assert "장면 블록의 감각·사물 재료 2개" in stage_machine.missing(s)
    s.materials += [_mat(6, "scene", "sense"), _mat(7, "scene", "object"),
                    _mat(8, "meaning", "interpretation")]
    assert stage_machine.is_ready_to_close(s)
    s.materials[-1].excluded = True  # 빼 둔 재료는 세지 않는다
    assert "의미 블록의 당신 자신의 말" in stage_machine.missing(s)


def test_stage3_outline_must_start_with_scene_and_end_with_resonance() -> None:
    s = _session(3)
    s.materials += [_mat(1, "scene"), _mat(2, "resonance")]
    s.outline_items += [
        OutlineItem(position=1, arc_block="scene", material_ids=["id1"]),
        OutlineItem(position=2, arc_block="resonance", material_ids=["id2"]),
    ]
    assert stage_machine.is_ready_to_close(s)
    s.outline_items[0].arc_block = "event"
    assert "장면으로 시작하는 첫 단락" in stage_machine.missing(s)


# ---------- prompt_builder ----------


def test_prompt_puts_stable_part_first_and_state_after() -> None:
    s = _session(1)
    s.turns[0].role = "coach"  # 코치가 먼저 연 대화
    s.turns.append(Turn(idx=1, role="user", text="회의실이었어요", stage=1))
    s.signals.append(Signal(kind="skipped", value="어머니 이야기"))
    prompt = prompt_builder.build(s, feedback="다시 써라")
    (stable,) = prompt["system"]
    state = prompt["messages"][-1]["content"][-1]
    assert stable["cache_control"]["type"] == "ephemeral"
    assert "다섯 가지 철칙" in stable["text"] and "1단계. 주제 설정" in stable["text"]
    assert "자동 생성 파일" not in stable["text"]  # 안내 주석은 모델에 안 보낸다
    assert "어머니 이야기" in state["text"] and state["text"].endswith("다시 써라")
    assert [m["role"] for m in prompt["messages"]] == ["user", "assistant", "user"]


def test_stage_module_switches_with_stage() -> None:
    assert "4단계. 태그와 교정" in prompt_builder.stable_system(4)
    assert "1단계. 주제 설정" not in prompt_builder.stable_system(4)


def test_rule_check_quote_must_be_verbatim() -> None:
    users = ["마지막에 그 자국을 손으로 한 번 쓸어 봤어요."]
    bad = reviewer.rule_check("‘한 번 쓸어 봤다’고 하셨어요. 그때 손끝에 뭐가 느껴졌어요?", users)
    assert any("인용" in r for r in bad)
    ok = reviewer.rule_check("‘한 번 쓸어 봤어요’라고 하셨어요. 그때 손끝에 뭐가 느껴졌어요?", users)
    assert ok == []


def test_rule_check_repeated_question() -> None:
    prev = "그 말을 처음 들은 날, 엄마는 어디를 보고 계셨어요?"
    again = "‘그...’ 하고 멈추셨어요. 그 말을 처음 들은 날, 엄마는 어디를 보고 계셨어요?"
    assert any("되풀이" in r for r in reviewer.rule_check(again, previous_question=prev))
    other = "‘그...’ 하고 멈추셨어요. 모니터에는 무엇이 떠 있었어요?"
    assert reviewer.rule_check(other, previous_question=prev) == []


def test_ensure_dialogue_adds_missed_quote_verbatim() -> None:
    from app.engine.extractor import ensure_dialogue

    utter = '엄마가 "이런 걸 요즘 누가 사냐"면서도 그 자리에서 입어 보셨어요.'
    raw = Extraction(materials=[
        ExtractedMaterial(text="그 자리에서 입어 보셨어요", type="scene", arc_block="scene"),
    ])
    out = ensure_dialogue(raw, utter)
    dialogue = [m for m in out.materials if m.type == "dialogue"]
    assert [m.text for m in dialogue] == ['"이런 걸 요즘 누가 사냐"']
    assert dialogue[0].text in utter and dialogue[0].arc_block == "event"


def test_ensure_dialogue_keeps_existing_and_fills_block() -> None:
    from app.engine.extractor import ensure_dialogue

    utter = '"이번 분기만 버티자." 그 말을 3년 동안 들었어요.'
    raw = Extraction(materials=[
        ExtractedMaterial(text='"이번 분기만 버티자."', type="dialogue", arc_block=None),
    ])
    out = ensure_dialogue(raw, utter)
    assert len(out.materials) == 1 and out.materials[0].arc_block == "event"


def test_prompt_caches_history_with_state_at_end() -> None:
    """비용: 상태는 대화 뒤 system 메시지로, 캐시 표시는 마지막 사용자 말에."""
    s = _session(1)
    s.turns[0].role = "coach"
    s.turns.append(Turn(idx=1, role="user", text="회의실이었어요", stage=1))
    prompt = prompt_builder.build(s, feedback="다시 써라", model="claude-sonnet-5-5")
    assert prompt["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    *_history, last_user, state = prompt["messages"]
    assert last_user["role"] == "user"
    assert last_user["content"][-1]["cache_control"] == {"type": "ephemeral"}
    assert state["role"] == "system" and state["content"].endswith("다시 써라")
    # 대화 중간 system을 못 받는 모델: 상태는 마지막 사용자 말의 캐시 표시 뒤 블록
    haiku = prompt_builder.build(s, feedback="다시 써라", model="claude-haiku-4-5-20251001")
    assert len(haiku["system"]) == 1
    cached, tail = haiku["messages"][-1]["content"]
    assert haiku["messages"][-1]["role"] == "user"
    assert cached["cache_control"] == {"type": "ephemeral"} and cached["text"] == "회의실이었어요"
    assert "cache_control" not in tail and tail["text"].endswith("다시 써라")


@pytest.mark.parametrize(
    ("text", "trivial"),
    [("네", True), ("맞아요.", True), ("모르겠어요", True), ("넘어갈게요", False),
     ("싫어요", False), ('"그만"', False), ("죽고 싶어", False),
     ("회의실이었어요. 창밖만 봤어요.", False)],
)
def test_trivial_replies_skip_extraction(text: str, trivial: bool) -> None:
    from app.engine.pipeline import _trivial

    assert _trivial(text) is trivial
