# Claude Code 구현 가이드: 「한 장면」

> 이 문서는 Claude Code에 그대로 넘겨 서비스를 단계별로 만들기 위한 실행 설계서입니다.
> 함께 쓰는 파일: `scene-essay-coach/SKILL.md` (대화 원칙), `service-plan.md` (기획안)

---

## 0. 진행 방식 요약

1. 새 저장소를 만들고 이 문서와 스킬 문서를 넣는다.
2. 저장소 루트에 `CLAUDE.md`를 둔다 (4장 템플릿).
3. 12장의 **Phase별 프롬프트**를 Claude Code에 하나씩 붙여 넣는다. 한 Phase가 끝나면 테스트를 돌리고 커밋한 뒤 다음으로 간다.
4. 큰 Phase는 먼저 계획을 세우게 하고(계획 모드 활용), 계획을 확인한 뒤 구현을 승인한다.

Claude Code 사용법은 공식 문서를 기준으로 한다: https://docs.claude.com/en/docs/claude-code/overview

---

## 1. 기술 스택

| 영역 | 선택 | 이유 |
|---|---|---|
| 백엔드 | Python 3.11+, FastAPI | 비동기 스트리밍, Anthropic Python SDK, STT 연동이 쉬움 |
| LLM | Anthropic Claude API | 질문자·초안: `claude-sonnet-5-5` / 추출·검수: `claude-haiku-4-5-20251001` |
| 프론트엔드 | React + Vite + TypeScript | 단일 페이지 대화 UI, 음성 녹음 |
| DB | SQLite (개발) → PostgreSQL (운영) | SQLAlchemy로 전환 비용 최소화 |
| STT | 교체 가능한 어댑터 구조 | Whisper 계열, CLOVA Speech, Google STT 등 비교 후 선택 |
| 배포 | 프론트 Vercel / 백엔드 Render·Fly.io 등 | 단계적으로 결정 |

> 모델 이름과 가격은 바뀔 수 있으니 구현 시점에 https://docs.claude.com 에서 확인한다. 모델 이름은 코드에 하드코딩하지 말고 환경 변수로 둔다.

---

## 2. 준비물

- Anthropic API 키 → `.env`의 `ANTHROPIC_API_KEY`
- STT API 키 (선택한 서비스)
- Node.js, Python, Git
- Claude Code 설치 (공식 문서 기준)

---

## 3. 저장소 구조

```
one-scene/
├── CLAUDE.md                         # Claude Code가 매번 읽는 프로젝트 규칙
├── .claude/
│   └── skills/
│       └── scene-essay-coach/
│           └── SKILL.md              # 개발 중 Claude Code도 참고하는 대화 원칙 원본
├── docs/
│   ├── service-plan.md
│   └── claude-code-guide.md          # 이 문서
├── backend/
│   ├── app/
│   │   ├── main.py                   # FastAPI 진입점
│   │   ├── config.py                 # 환경 변수, 모델 이름
│   │   ├── db.py                     # SQLAlchemy 세션
│   │   ├── models.py                 # ORM 모델
│   │   ├── schemas.py                # Pydantic 스키마
│   │   ├── routers/
│   │   │   ├── sessions.py           # 세션 생성/조회/단계 이동
│   │   │   ├── turns.py              # 대화 턴 (스트리밍)
│   │   │   ├── drafts.py             # 초안 조립, 교정
│   │   │   ├── voice.py              # 음성 업로드 → STT
│   │   │   └── library.py            # 보관함, 태그
│   │   ├── engine/
│   │   │   ├── prompt_builder.py     # SKILL.md 섹션 + 단계 모듈 + 상태 조립
│   │   │   ├── questioner.py         # 질문 생성
│   │   │   ├── extractor.py          # 재료 추출 (JSON)
│   │   │   ├── reviewer.py           # 질문 품질 검수
│   │   │   ├── stage_machine.py      # 단계 마감 조건 판정
│   │   │   ├── assembler.py          # 초안 조립 (출처 ID 필수)
│   │   │   ├── fidelity.py           # 진실성 검사
│   │   │   └── cliche_linter.py      # 규칙 기반 상투어·과장어 검사
│   │   ├── prompts/
│   │   │   ├── core.md               # 철칙·응답 형식·파고들기 기법 (SKILL.md 1~3장)
│   │   │   ├── stage1_topic.md
│   │   │   ├── stage2_paragraph.md
│   │   │   ├── stage3_sequence.md
│   │   │   ├── stage4_revise.md
│   │   │   ├── extractor.md
│   │   │   ├── reviewer.md
│   │   │   ├── assembler.md
│   │   │   └── fidelity.md
│   │   ├── data/
│   │   │   └── cliches.yaml          # 상투어·과장어·감정어 사전 (SKILL.md 7장)
│   │   └── stt/
│   │       ├── base.py               # STT 인터페이스
│   │       └── provider_x.py         # 실제 구현
│   └── tests/
│       ├── golden/                   # 모범 대화 시나리오
│       ├── test_reviewer.py
│       ├── test_linter.py
│       └── test_fidelity.py
└── frontend/
    └── src/
        ├── pages/
        │   ├── Chat.tsx              # 메인 대화 화면
        │   ├── Draft.tsx             # 초안·교정 화면
        │   └── Library.tsx           # 보관함
        ├── components/
        │   ├── StageBar.tsx          # 4단계 진행 바
        │   ├── ArcPanel.tsx          # 서사 아크 5블록 채움 상태
        │   ├── MaterialCard.tsx      # 재료 카드
        │   ├── MicButton.tsx         # 길게 눌러 말하기
        │   └── HighlightedDraft.tsx  # 상투어·빈칸 하이라이트
        └── api/client.ts
```

---

## 4. `CLAUDE.md` 템플릿

저장소 루트에 그대로 넣는다.

```markdown
# 한 장면 (One Scene) — 프로젝트 규칙

## 이 서비스가 무엇인가
AI가 글을 대신 쓰지 않고, 한 번에 하나씩 질문해 사용자의 기억 속 장면을 끌어내는
대화형 글쓰기 서비스. 대화 원칙의 원본은 .claude/skills/scene-essay-coach/SKILL.md.
제품 동작을 바꾸는 코드를 쓸 때는 반드시 이 스킬 문서를 먼저 읽는다.

## 절대 깨지면 안 되는 제품 규칙
1. 질문자 응답에는 질문이 정확히 하나. reviewer가 이를 검사한다.
2. 초안의 모든 문장은 materials 테이블의 재료 ID에 연결되어야 한다.
   연결되지 않는 문장은 [빈칸: 질문]으로 바꾼다. 절대 지어내지 않는다.
3. 사용자 발화 원문은 수정하지 않고 저장한다 (materials.text).
4. 단계 이동은 사용자가 버튼이나 말로 승인할 때만 일어난다.

## 코드 규칙
- 백엔드: FastAPI, SQLAlchemy 2.x, Pydantic v2, 타입 힌트 필수
- 모델 이름은 config.py의 환경 변수로만 참조 (하드코딩 금지)
- 프롬프트는 backend/app/prompts/*.md 파일로 관리. 코드 안 문자열 금지
- LLM 호출은 engine/ 안에서만. 라우터에서 직접 호출 금지
- 프론트: React + TypeScript, 상태는 서버가 원천

## 작업 방식
- 새 기능 전에 계획을 먼저 보여주고 승인을 받는다
- 기능마다 테스트를 쓴다. 특히 reviewer, linter, fidelity는 테스트 필수
- 한 Phase가 끝나면 pytest와 프론트 빌드를 모두 통과시킨 뒤 커밋

## 명령어
- 백엔드 실행: cd backend && uvicorn app.main:app --reload
- 테스트: cd backend && pytest
- 프론트: cd frontend && npm run dev
```

---

## 5. 데이터 모델

```sql
-- 글쓰기 세션 (글 한 편 = 세션 하나)
CREATE TABLE sessions (
  id              TEXT PRIMARY KEY,
  user_id         TEXT NOT NULL,
  stage           INTEGER NOT NULL DEFAULT 1,       -- 1~4
  topic_sentence  TEXT,                              -- 사용자 원문
  target_length   TEXT CHECK (target_length IN ('short','medium','long')),
  sequence_pattern TEXT,                             -- linear/return/frame/cross
  status          TEXT NOT NULL DEFAULT 'active',    -- active/paused/done
  created_at      TIMESTAMP, updated_at TIMESTAMP
);

-- 대화 턴
CREATE TABLE turns (
  id          TEXT PRIMARY KEY,
  session_id  TEXT REFERENCES sessions(id),
  idx         INTEGER NOT NULL,
  role        TEXT CHECK (role IN ('user','coach')),
  text        TEXT NOT NULL,
  input_mode  TEXT CHECK (input_mode IN ('voice','text')),
  stage       INTEGER NOT NULL,
  created_at  TIMESTAMP
);

-- 재료: 사용자 발화에서 추출, 원문 보존
CREATE TABLE materials (
  id          TEXT PRIMARY KEY,          -- m1, m2 ...
  session_id  TEXT REFERENCES sessions(id),
  turn_id     TEXT REFERENCES turns(id),
  text        TEXT NOT NULL,             -- 사용자 원문 그대로
  type        TEXT CHECK (type IN ('scene','object','sense','dialogue','person','fact','interpretation','time','place')),
  arc_block   TEXT CHECK (arc_block IN ('scene','event','meaning','present','resonance')),
  emotion_word BOOLEAN DEFAULT FALSE,    -- 감정 명명이 포함된 재료
  excluded    BOOLEAN DEFAULT FALSE      -- 사용자가 빼기로 한 재료
);

-- 반복된 말, 열린 틈, 넘어간 주제
CREATE TABLE signals (
  id          TEXT PRIMARY KEY,
  session_id  TEXT REFERENCES sessions(id),
  kind        TEXT CHECK (kind IN ('repeated','gap','skipped','hesitation')),
  value       TEXT NOT NULL,
  count       INTEGER DEFAULT 1,
  resolved    BOOLEAN DEFAULT FALSE
);

-- 단락 개요 (3단계 산출물)
CREATE TABLE outline_items (
  id          TEXT PRIMARY KEY,
  session_id  TEXT REFERENCES sessions(id),
  position    INTEGER NOT NULL,
  arc_block   TEXT,
  material_ids TEXT,                     -- JSON 배열
  target_chars INTEGER
);

-- 초안 (버전별)
CREATE TABLE drafts (
  id          TEXT PRIMARY KEY,
  session_id  TEXT REFERENCES sessions(id),
  version     INTEGER NOT NULL,
  body        TEXT NOT NULL,
  sentence_map TEXT NOT NULL,            -- JSON: [{sentence, material_ids, is_blank}]
  lint_result TEXT,                      -- JSON
  created_at  TIMESTAMP
);

-- 태그 (4단계)
CREATE TABLE tags (
  session_id  TEXT REFERENCES sessions(id),
  kind        TEXT CHECK (kind IN ('period','person','place','object','gap')),
  value       TEXT NOT NULL
);
```

---

## 6. API 설계

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/sessions` | 새 글 시작 → 첫 질문 반환 |
| GET | `/sessions/{id}` | 세션 상태 (단계, 아크 채움, 신호) |
| POST | `/sessions/{id}/turns` | 사용자 발화 전송 → 코치 질문 스트리밍 (SSE) |
| POST | `/sessions/{id}/voice` | 음성 파일 → STT 텍스트 반환 (전송 전 사용자 확인용) |
| GET | `/sessions/{id}/material-card` | 현재 단계 재료 카드 |
| POST | `/sessions/{id}/advance` | 사용자 승인으로 다음 단계 이동 |
| POST | `/sessions/{id}/back` | 이전 단계로 |
| POST | `/sessions/{id}/outline` | 단락 개요 저장 |
| POST | `/sessions/{id}/drafts` | 초안 조립 요청 |
| POST | `/drafts/{id}/lint` | 상투어·과장어·감정어 + 진실성 검사 |
| POST | `/drafts/{id}/revise-question` | 하이라이트 문장 → 교정 질문 하나 |
| POST | `/sessions/{id}/tags` | 태그 저장, 열린 틈 정리 |
| GET | `/library` | 완성 글, 태그, 열린 틈 목록 |

---

## 7. 대화 엔진 파이프라인

한 턴이 처리되는 순서.

```python
async def handle_user_turn(session_id: str, text: str, input_mode: str):
    session = load_session(session_id)
    user_turn = save_turn(session, role="user", text=text, input_mode=input_mode)

    # 1) 재료 추출 (경량 모델, JSON 출력) — 원문 보존
    extracted = await extractor.run(text, session_state(session))
    save_materials(session, user_turn, extracted.materials)
    update_signals(session, extracted.repeated, extracted.hesitations, extracted.skip_request)

    # 2) 사용자가 넘어가자고 했는지 우선 처리
    if extracted.skip_request:
        mark_skipped(session, extracted.skip_topic)

    # 3) 단계 마감 조건 판정 → 충족 시 질문 대신 재료 카드 제안
    if stage_machine.is_ready_to_close(session):
        return propose_material_card(session)

    # 4) 질문 생성 (최대 3회 시도)
    prompt = prompt_builder.build(session)   # core.md + stageN.md + 상태 YAML + 최근 대화
    for attempt in range(3):
        question = await questioner.run(prompt)
        review = await reviewer.run(question, last_user_text=text, stage=session.stage)
        if review.passed:
            break
        prompt = prompt_builder.with_feedback(prompt, review.reasons)

    save_turn(session, role="coach", text=question)
    return question
```

### 질문 검수기 판정 기준 (reviewer)
SKILL.md 3장의 품질 기준을 그대로 JSON 판정으로 바꾼다.

```json
{
  "single_question": true,
  "quotes_or_follows_user": true,
  "concrete_not_abstract": true,
  "not_leading": true,
  "no_summary_or_advice": true,
  "no_empathy_cliche": true,
  "passed": true,
  "reasons": []
}
```
- `single_question`은 규칙으로 먼저 검사한다 (물음표 개수, "그리고 ~요?" 패턴). LLM 판정은 그 다음.
- 실패 사유는 다음 시도의 프롬프트에 피드백으로 넣는다.

### 재료 추출기 출력 스키마 (extractor)
```json
{
  "materials": [
    {"text": "이번 분기만 버티자", "type": "dialogue", "arc_block": "event", "emotion_word": false}
  ],
  "repeated": ["창밖"],
  "hesitations": ["그때 그... 뭐랄까"],
  "skip_request": false,
  "skip_topic": null
}
```
- 추출기 프롬프트 핵심 규칙: `text`는 사용자 발화의 **연속된 부분 문자열**이어야 한다. 서버에서 `text in user_utterance`로 검증하고, 실패한 항목은 버린다. 이것이 "지어내지 않기"의 첫 번째 방어선이다.

---

## 8. 초안 조립과 진실성 검사

### 조립기 출력 형식
```json
{
  "paragraphs": [
    {
      "outline_position": 1,
      "sentences": [
        {"text": "회의실 창밖으로 주차장이 보였다.", "material_ids": ["m3","m4"], "is_blank": false},
        {"text": "[빈칸: 그날 창밖의 날씨는 어땠나요?]", "material_ids": [], "is_blank": true}
      ]
    }
  ]
}
```

### 진실성 검사 (fidelity)
1. **구조 검사**: `is_blank=false`인 문장에 `material_ids`가 비어 있으면 실패.
2. **의미 검사**: 각 문장과 연결된 재료 원문을 함께 LLM에 보내 "재료에 없는 사실, 사물, 감각, 대사, 감정이 추가되었는가"를 판정.
3. 실패한 문장은 자동으로 `[빈칸: …]`으로 바꾸고, 그 빈칸에 들어갈 질문을 생성한다.

---

## 9. 상투어 린터

```python
# backend/app/engine/cliche_linter.py
import re, yaml
from dataclasses import dataclass

@dataclass
class LintHit:
    kind: str        # cliche | exaggeration | emotion_name | long_sentence | weak_opening | moral_ending
    span: tuple[int, int]
    text: str
    question: str    # 사용자에게 보낼 교정 질문 템플릿

def lint(body: str, dictionary_path: str) -> list[LintHit]:
    d = yaml.safe_load(open(dictionary_path, encoding="utf-8"))
    hits: list[LintHit] = []
    for kind in ("cliche", "exaggeration", "emotion_name"):
        for entry in d[kind]:
            for m in re.finditer(entry["pattern"], body):
                hits.append(LintHit(kind, m.span(), m.group(), entry["question"]))
    # 60자 넘는 문장
    for m in re.finditer(r"[^.!?\n]{61,}[.!?]", body):
        hits.append(LintHit("long_sentence", m.span(), m.group(), "이 문장을 두 동작으로 나눌 수 있을까요?"))
    # 마지막 문장 교훈 선언
    last = body.strip().split("\n")[-1]
    if re.search(r"(깨달았다|알게 되었다|해야 한다|살아가고 싶다)\.?$", last):
        hits.append(LintHit("moral_ending", (len(body)-len(last), len(body)), last,
                            "처음 장면의 사물을 지금 다시 본다면, 어디서 어떤 모습이에요?"))
    return hits
```

`cliches.yaml` 예시:
```yaml
emotion_name:
  - pattern: "(슬펐다|슬펐고|기뻤다|외로웠다|허전했다|설렜다|불안했다|서운했다)"
    question: "'{match}'라고 쓰셨어요. 그때 실제로 몸은 무엇을 하고 있었어요?"
cliche:
  - pattern: "가슴이 (먹먹|뭉클)"
    question: "그 순간 눈에 들어온 게 뭐였어요?"
  - pattern: "시간이 쏜살같이|어느덧|눈 깜짝할 사이"
    question: "그 시간 동안 달라진 물건이나 습관이 있어요?"
  - pattern: "(인생의 전환점|소중한 깨달음|한 뼘 성장)"
    question: "그 일 이후로 실제로 달라진 행동 하나만 말해주실래요?"
exaggeration:
  - pattern: "(너무너무|정말 엄청|세상에서 가장|평생 잊지 못할)"
    question: "강조 대신 그 장면의 디테일 하나를 넣는다면 뭐가 좋을까요?"
```

---

## 10. 단계 마감 조건 (stage_machine)

| 단계 | 마감 조건 (모두 충족) |
|---|---|
| 1 | `topic_sentence` 있음, `arc_block=scene` 재료 1개 이상, `target_length` 있음 |
| 2 | 아크 5블록 각각 재료 1개 이상, scene 블록에 sense/object 재료 2개 이상, meaning 블록에 interpretation 재료 1개 이상 |
| 3 | `outline_items` 저장됨, 첫 항목이 scene 블록, 마지막 항목에 resonance 재료 |
| 4 | 최신 초안의 fidelity 통과, `is_blank` 0개 (또는 사용자가 빈칸 유지 승인), 태그 저장 |

조건 충족은 **제안**일 뿐이다. 실제 이동은 `/advance` 호출(사용자 승인) 때만 일어난다.

---

## 11. 프론트엔드 핵심 동작

- **MicButton**: 길게 누르면 `MediaRecorder` 녹음 → 떼면 `/voice` 업로드 → 텍스트를 입력창에 채움 → 사용자가 확인 후 전송. (말한 내용이 바로 전송되지 않게 해 인식 오류를 잡는다)
- **질문 표시**: 가장 최근 코치 질문을 화면 중앙에 크게, 이전 대화는 흐리게.
- **ArcPanel**: 블록별 재료 개수, 반복된 말 상위 3개, 열린 틈.
- **MaterialCard**: 단계 마감 제안 시 모달. 재료 원문 목록 + "다음 단계로" / "조금 더 이야기하기" 버튼.
- **HighlightedDraft**: 린트 결과를 색으로 표시, 클릭 시 `/revise-question` 호출해 질문 하나 표시.
- **넘어가기 버튼**: 대화 화면 상시 노출. 누르면 `skipped` 신호 저장 후 다른 블록 질문.

---

## 12. Phase별 Claude Code 프롬프트

각 Phase를 순서대로 붙여 넣는다. 끝나면 테스트 통과 확인 → 커밋.

### Phase 0. 저장소 세팅
```
docs/claude-code-guide.md의 3장 구조대로 저장소 뼈대를 만들어줘.
CLAUDE.md는 4장 템플릿을 그대로 넣고, .claude/skills/scene-essay-coach/SKILL.md는
내가 넣어둔 파일을 사용해. 백엔드는 FastAPI 헬스체크 엔드포인트,
프론트는 Vite React TS 기본 화면까지만. .env.example도 만들어줘.
먼저 계획을 보여주고 승인받은 뒤 진행해.
```

### Phase 1. 데이터 모델과 세션 API
```
5장 데이터 모델을 SQLAlchemy 2.x ORM으로 구현하고 SQLite로 시작해.
6장 API 중 /sessions, /sessions/{id}, /advance, /back만 먼저 만들어.
advance는 사용자 승인으로만 동작해야 하고, 각 엔드포인트에 pytest를 써줘.
```

### Phase 2. 프롬프트 파일 분리
```
.claude/skills/scene-essay-coach/SKILL.md를 읽고 backend/app/prompts/ 아래로 나눠줘.
core.md에는 0~3장(정체성, 철칙, 구술 모드, 대화 운영)과 8장(금지 사항), 9장(정서적 안전),
stage1~4.md에는 5장의 각 단계 섹션과 4장 서사 아크, 6장 길이 기준 중 해당 부분.
cliches.yaml은 7장 목록을 9장 예시 형식으로 변환해.
원문의 의미를 바꾸지 말고, 바꾼 부분이 있으면 목록으로 알려줘.
```

### Phase 3. 대화 엔진
```
7장 파이프라인대로 engine/ 모듈을 구현해: prompt_builder, extractor, questioner,
reviewer, stage_machine. extractor의 materials.text는 사용자 발화의 부분 문자열인지
서버에서 검증하고 아닌 건 버려. reviewer는 질문 개수를 규칙으로 먼저 검사한 뒤
LLM으로 판정하고, 실패하면 최대 3회 재생성해.
/sessions/{id}/turns를 SSE 스트리밍으로 만들어.
tests/golden/에 SKILL.md 10장 대화 예시를 시나리오로 넣고, 각 코치 응답이
reviewer를 통과하는지 테스트해.
```

### Phase 4. 프론트엔드 대화 화면
```
11장대로 Chat.tsx, StageBar, ArcPanel, MaterialCard, MicButton을 만들어.
service-plan.md 8장 화면 구성을 따르고, 모바일에서는 ArcPanel을 하단 시트로.
질문은 한 번에 하나만 크게 보여야 해. 넘어가기 버튼 상시 노출.
```

### Phase 5. 음성 입력
```
stt/base.py에 STT 인터페이스를 만들고 [선택한 STT 서비스] 어댑터를 구현해.
/voice는 텍스트만 반환하고 자동 전송하지 않아. 음성 원본은 변환 후 삭제가 기본값.
MicButton과 연결하고, 한국어 고유명사 오인식 대비로 사용자 사전 필드를 남겨둬.
```

### Phase 6. 단락 개요, 초안, 교정
```
8~9장대로 assembler, fidelity, cliche_linter를 구현하고 /outline, /drafts,
/lint, /revise-question을 만들어. 출처 없는 문장은 반드시 [빈칸: 질문]으로 바뀌어야 해.
테스트: (1) 재료에 없는 날씨를 넣은 가짜 초안이 fidelity에서 걸리는지
(2) cliches.yaml 항목이 모두 탐지되는지 (3) 교훈 선언 마지막 문장이 걸리는지.
Draft.tsx와 HighlightedDraft를 만들고, 문장 클릭 시 출처 재료가 보이게 해.
```

### Phase 7. 태그와 보관함
```
4단계 태그 저장과 Library.tsx를 만들어. 열린 틈(gap)은 보관함에서
"다음 글감"으로 보여주고, 누르면 그 틈을 첫 질문으로 새 세션을 시작해.
```

### Phase 8. 평가와 다듬기
```
tests/golden/에 시나리오 10개를 더 만들어 (퇴사, 이사, 부모님, 첫 월급, 버리지 못한 물건 등).
각 시나리오에서 코치 응답의 질문 품질 지표(service-plan.md 10장)를 계산하는
스크립트 scripts/eval_questions.py를 만들고 결과를 표로 출력해.
목표 미달 항목은 프롬프트 수정 제안과 함께 보고해.
```

---

## 13. 평가 체계

### 자동 평가 (매 커밋)
| 항목 | 방법 | 기준 |
|---|---|---|
| 질문 1개 | 규칙 검사 | 98% 이상 |
| 직전 발화 이어받기 | LLM 판정 | 85% 이상 |
| 재료 원문 보존 | 부분 문자열 검사 | 100% |
| 초안 출처 연결 | 구조 검사 | 100% |
| 상투어 탐지 | 사전 테스트 | 전 항목 탐지 |

### 사람 평가 (주 1회)
- 실제 대화 로그 10건을 뽑아 "어느 대답 뒤에 붙여도 되는 질문"을 표시한다. 이 비율이 핵심 개선 지표다.
- 완성 글을 쓴 사람에게 "내 이야기 같다" 5점 척도로 묻는다.

---

## 14. 착수 체크리스트

- [ ] 새 저장소 생성, `docs/`에 기획안·가이드, `.claude/skills/`에 SKILL.md
- [ ] `CLAUDE.md` 작성
- [ ] API 키 준비, `.env` 설정
- [ ] STT 서비스 2~3곳 한국어 인식률 비교 (본인 음성 3분 샘플)
- [ ] Phase 0 프롬프트 실행
- [ ] Phase 3 끝나면 직접 글 한 편 완주해보기 (가장 중요한 검증)
