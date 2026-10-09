import re
from pathlib import Path

import pytest
import yaml

from app import prompt_sync

CLICHES_PATH = Path(prompt_sync.__file__).parent / "data" / "cliches.yaml"
KINDS = ("emotion_name", "cliche", "exaggeration")


def test_prompt_files_match_skill_md() -> None:
    """프롬프트 파일은 SKILL.md에서 생성한 그대로여야 한다. 실패하면 prompt_sync를 다시 실행."""
    for name, text in prompt_sync.render().items():
        on_disk = (prompt_sync.PROMPTS_DIR / name).read_text(encoding="utf-8")
        assert on_disk == text, f"{name}: uv run python -m app.prompt_sync 실행 필요"


def test_every_skill_section_is_used() -> None:
    """SKILL.md의 0~10장이 어느 프롬프트 파일엔가 들어갔는지 (11장은 구현 참고용이라 제외)."""
    used = {chapter for plan in prompt_sync.PLAN.values() for chapter, _ in plan}
    assert used == set(range(11))


def test_prompt_text_is_verbatim_from_skill() -> None:
    """생성 파일의 본문 줄은 모두 SKILL.md에 그대로 있는 줄이어야 한다 (안내문·구분선 제외)."""
    skill_lines = set(prompt_sync.SKILL_PATH.read_text(encoding="utf-8").splitlines())
    allowed = {prompt_sync.GENERATED_NOTICE, prompt_sync.CHAPTER_NOTE, "---", ""}
    for name, text in prompt_sync.render().items():
        for line in text.splitlines():
            assert line in skill_lines or line in allowed, f"{name}: 원문에 없는 줄 {line!r}"


def _entries() -> list[tuple[str, dict]]:
    data = yaml.safe_load(CLICHES_PATH.read_text(encoding="utf-8"))
    return [(kind, entry) for kind in KINDS for entry in data[kind]]


@pytest.mark.parametrize(
    ("kind", "entry"), _entries(), ids=lambda v: v if isinstance(v, str) else v["pattern"][:20]
)
def test_cliche_entry_is_well_formed(kind: str, entry: dict) -> None:
    pattern = re.compile(entry["pattern"])
    assert entry["label"]
    question = entry["question"].format(match="X")
    assert question.count("?") == 1, "교정 질문은 정확히 하나 (철칙 1)"
    for example in entry["examples"]:
        assert pattern.search(example), f"{kind}: 예문을 못 잡음 {example!r}"


def test_cliche_dictionary_covers_skill_chapter_7() -> None:
    """SKILL.md 7장(및 출처 표시된 다른 장)의 표현이 사전 어딘가에서 탐지되어야 한다."""
    patterns = [re.compile(entry["pattern"]) for _, entry in _entries()]
    sources = [s for _, entry in _entries() for s in entry["source"]]
    skill = prompt_sync.SKILL_PATH.read_text(encoding="utf-8")
    for phrase in sources:
        core = phrase.replace("~", "")
        assert core.strip(" 의하며") in skill or phrase in skill, f"SKILL.md에 없는 출처 {phrase!r}"
        sample = phrase.replace("~", "가족") + " "
        assert any(p.search(sample) for p in patterns), f"탐지 못 함: {phrase!r}"
