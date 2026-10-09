"""prompts/*.md, data/*.yaml 로더."""

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

APP_DIR = Path(__file__).resolve().parent.parent
PROMPTS_DIR = APP_DIR / "prompts"
DATA_DIR = APP_DIR / "data"

_HTML_COMMENT = re.compile(r"<!--.*?-->\s*", re.DOTALL)


@lru_cache
def prompt(name: str) -> str:
    """프롬프트 파일. 자동 생성 안내 같은 HTML 주석은 모델에 보내지 않는다."""
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    return _HTML_COMMENT.sub("", text).strip()


@lru_cache
def data(name: str) -> Any:
    with open(DATA_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)
