"""규칙 기반 교정 점검 (모델 없음). 사전: data/cliches.yaml. 원본: SKILL.md 4-2, 6장, 7장.

초안은 조립기가 이미 문장 단위로 나눠 주므로 문장 경계를 정규식으로 추측하지 않는다
(open-questions C2·C3: 마침표 없는 문장, 마지막 '줄' 대신 마지막 '문장').
"""

import re
from dataclasses import asdict, dataclass

from app.engine import resources

MAX_SENTENCE_CHARS = 60  # 6장: 60자를 넘는 문장은 나눌 수 있는지 확인
MORAL_ENDING = re.compile(
    r"(깨달았다|깨닫게 되었다|알게 되었다|알게 됐다|해야 한다|해야겠다|살아가고 싶다|느꼈다|배웠다)[.!]?$"
)
BLANK = re.compile(r"^\[빈칸:\s*(.+?)\]$")

WHY = {
    "cliche": "감정을 대신하는 익숙한 표현이에요.",
    "exaggeration": "강조하는 말이 장면을 가리고 있어요.",
    "emotion_name": "감정의 이름이 장면 대신 들어가 있어요.",
    "long_sentence": "한 문장이 60자를 넘어요.",
    "moral_ending": "마지막 문장이 깨달음을 말로 정리하고 있어요.",
    "blank": "대화에 없던 내용이라 지어내지 않고 비워 두었어요.",
}
LABEL = {
    "long_sentence": "긴 문장",
    "moral_ending": "교훈으로 닫는 끝",
    "blank": "재료가 없는 자리",
}


@dataclass
class LintHit:
    id: str
    kind: str  # cliche | exaggeration | emotion_name | long_sentence | moral_ending | blank
    label: str
    sentence: int  # 문장 번호 (sentence_map 인덱스)
    start: int
    end: int
    text: str
    why: str
    question: str
    dismissed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _hit(kind: str, label: str, sentence: int, start: int, end: int, text: str,
         question: str) -> LintHit:
    return LintHit(
        id=f"{sentence}:{start}:{kind}", kind=kind, label=label, sentence=sentence,
        start=start, end=end, text=text, why=WHY[kind], question=question,
    )


def lint_sentences(sentences: list[str], blanks: list[bool] | None = None) -> list[LintHit]:
    dictionary = resources.data("cliches")
    blanks = blanks or [False] * len(sentences)
    hits: list[LintHit] = []
    for i, sentence in enumerate(sentences):
        if blanks[i]:
            m = BLANK.match(sentence.strip())
            question = m.group(1) if m else "이 자리에 들어갈 장면을 말해 주실래요?"
            hits.append(_hit("blank", LABEL["blank"], i, 0, len(sentence), sentence, question))
            continue
        taken: list[tuple[int, int]] = []
        for kind in ("cliche", "emotion_name", "exaggeration"):
            for entry in dictionary[kind]:
                for m in re.finditer(entry["pattern"], sentence):
                    if any(s < m.end() and m.start() < e for s, e in taken):
                        continue  # 이미 더 구체적인 항목이 잡은 자리
                    taken.append(m.span())
                    hits.append(
                        _hit(kind, entry["label"], i, m.start(), m.end(), m.group(),
                             entry["question"].format(match=m.group()))
                    )
        if len(sentence) > MAX_SENTENCE_CHARS:
            hits.append(
                _hit("long_sentence", LABEL["long_sentence"], i, 0, len(sentence), sentence,
                     "이 문장을 두 동작으로 나눌 수 있을까요?")
            )

    last = next((i for i in range(len(sentences) - 1, -1, -1) if not blanks[i]), None)
    if last is not None and MORAL_ENDING.search(sentences[last].strip()):
        s = sentences[last]
        hits.append(
            _hit("moral_ending", LABEL["moral_ending"], last, 0, len(s), s,
                 "처음 장면의 사물을 지금 다시 본다면, 어디서 어떤 모습이에요?")
        )
    hits.sort(key=lambda h: (h.sentence, h.start))
    return hits
