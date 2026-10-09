"""SKILL.md(원본) → backend/app/prompts/*.md 생성.

SKILL.md가 대화 원칙의 유일한 원본이다. 프롬프트 파일은 이 모듈이 SKILL.md를
장(##)·절(###) 단위로 잘라 원문 그대로 이어 붙여 만든다. 문장을 고쳐 쓰지 않는다.

    cd backend && uv run python -m app.prompt_sync          # 다시 생성
    cd backend && uv run python -m app.prompt_sync --check  # 동기화 여부만 검사

tests/test_prompt_sync.py가 생성 결과와 저장된 파일이 같은지 검사한다.
"""

import re
import sys
from pathlib import Path

from app.config import REPO_DIR

SKILL_PATH = REPO_DIR / ".claude" / "skills" / "scene-essay-coach" / "SKILL.md"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

GENERATED_NOTICE = (
    "<!-- 자동 생성 파일: .claude/skills/scene-essay-coach/SKILL.md에서 만든다. "
    "직접 고치지 말고 SKILL.md를 고친 뒤 `uv run python -m app.prompt_sync`를 실행한다. -->"
)

# 원문의 "n장" 참조가 파일을 나눈 뒤에도 뜻이 통하도록 붙이는 안내 (원문 수정 없음)
CHAPTER_NOTE = (
    "> 이 문서의 \"n장\"은 원본 스킬 문서의 장 번호다. "
    "4장 서사 아크는 이 문서에, 5장 각 단계 진행은 현재 단계 모듈에, "
    "6장 길이 기준과 7장 상투어 목록은 그것이 필요한 단계 모듈에 들어 있다."
)

# 파일별 구성: (장 번호, 단계 소제목 접두어 또는 None)
# - 장 번호만 쓰면 그 장 전체, 소제목 접두어를 주면 5장 안의 해당 단계 절만
PLAN: dict[str, list[tuple[int, str | None]]] = {
    "core.md": [(0, None), (1, None), (2, None), (3, None), (4, None), (8, None), (9, None),
                (10, None)],
    "stage1_topic.md": [(5, "intro"), (5, "1단계."), (6, None)],
    "stage2_paragraph.md": [(5, "intro"), (5, "2단계.")],
    "stage3_sequence.md": [(5, "intro"), (5, "3단계."), (6, None)],
    "stage4_revise.md": [(5, "intro"), (5, "4단계."), (6, None), (7, None)],
}

_FENCE = re.compile(r"^(```|~~~)")
_CHAPTER = re.compile(r"^## (\d+)\. ")


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.index("\n---", 3)
        return text[end + 4 :].lstrip("\n")
    return text


def _split_chapters(text: str) -> dict[int, list[str]]:
    """'## n. 제목' 단위로 줄 목록을 나눈다. 코드 블록 안의 #은 제목으로 보지 않는다."""
    chapters: dict[int, list[str]] = {}
    current: list[str] | None = None
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        match = None if in_fence else _CHAPTER.match(line)
        if match:
            current = chapters.setdefault(int(match.group(1)), [])
        if current is not None:
            current.append(line)
    return chapters


def _stage_parts(chapter5: list[str]) -> dict[str, list[str]]:
    """5장을 'intro'(첫 ### 앞)와 '### n단계.' 절로 나눈다."""
    parts: dict[str, list[str]] = {"intro": []}
    key = "intro"
    in_fence = False
    for line in chapter5:
        if _FENCE.match(line):
            in_fence = not in_fence
        if not in_fence and line.startswith("### "):
            key = line[4:].split(" ")[0]  # "1단계."
            parts[key] = []
        parts[key].append(line)
    return parts


def _clean(lines: list[str]) -> str:
    text = "\n".join(lines).strip("\n")
    # 장 끝의 구분선(---)은 파일 안에서 다시 붙인다
    text = re.sub(r"\n+---\s*$", "", text)
    return text.strip("\n")


def render() -> dict[str, str]:
    source = _strip_frontmatter(SKILL_PATH.read_text(encoding="utf-8"))
    chapters = _split_chapters(source)
    stages = _stage_parts(chapters[5])
    out: dict[str, str] = {}
    for filename, plan in PLAN.items():
        blocks: list[str] = []
        prev_chapter = None
        for chapter, part in plan:
            text = _clean(chapters[chapter] if part is None else stages[part])
            if chapter == prev_chapter:
                # 같은 장(5장 서론 + 단계 절)은 구분선 없이 잇는다
                blocks[-1] += "\n\n" + text
            else:
                blocks.append(text)
            prev_chapter = chapter
        header = [GENERATED_NOTICE]
        if filename == "core.md":
            header.append(CHAPTER_NOTE)
        out[filename] = "\n\n".join(header) + "\n\n" + "\n\n---\n\n".join(blocks) + "\n"
    return out


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    rendered = render()
    stale = [
        name
        for name, text in rendered.items()
        if not (PROMPTS_DIR / name).exists()
        or (PROMPTS_DIR / name).read_text(encoding="utf-8") != text
    ]
    if "--check" in argv:
        for name in stale:
            print(f"동기화 필요: {name}")
        return 1 if stale else 0
    PROMPTS_DIR.mkdir(exist_ok=True)
    for name, text in rendered.items():
        (PROMPTS_DIR / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"생성: {', '.join(rendered)} (변경 {len(stale)}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
