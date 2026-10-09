# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# 한 장면 (One Scene)

AI가 글을 대신 쓰지 않고, 한 번에 하나씩 질문해 사용자의 기억 속 장면을 끌어내는 대화형 글쓰기 서비스.
대화 원칙의 원본은 `.claude/skills/scene-essay-coach/SKILL.md`. 제품 동작을 바꾸는 코드를 쓸 때는 이 문서를 먼저 읽는다.
매 세션 시작 시 `docs/PROGRESS.md`에서 현재 위치를, 기능 착수 전 `docs/open-questions.md`에서 결정·미결 사항을 확인한다.

## 문서 지도
| 문서 | 내용 |
|---|---|
| `docs/service-plan.md` | 기획안 (기능 F1~F13, 성공 지표 10장, 로드맵) |
| `docs/claude-code-guide.md` | 구현 설계서 (DB, API, 파이프라인, Phase 0~8 프롬프트) |
| `docs/design/design-spec.md` | 목업(`docs/design/mockup.html`, 브라우저로 열기)에서 추출한 화면·디자인 토큰·문구 |
| `docs/prompt-mapping.md` | SKILL.md → 프롬프트 파일 매핑과 원문 대비 변경점 |
| `docs/open-questions.md` | 문서 간 불일치, 잠정 결정(A~E), 품질 문제(F) |
| `docs/PROGRESS.md` | 진행 체크리스트와 질문 품질 평가 기록 표 |

## 절대 깨지면 안 되는 제품 규칙
1. 코치 응답에는 질문이 정확히 하나. reviewer가 검사한다.
2. 초안의 모든 문장은 재료 ID에 연결된다. 연결되지 않는 문장은 `[빈칸: 질문]`으로 바꾼다. 절대 지어내지 않는다.
3. 사용자 발화 원문은 수정하지 않고 저장한다 (`materials.text`는 발화의 연속된 부분 문자열).
4. 단계 이동은 사용자가 승인할 때만 (`/advance`, `/back`, `/finish`는 `{"approved": true}` 필수).

## 작업 방식
- 새 기능 전에 계획을 먼저 보여주고 승인을 받는다.
- 기능마다 테스트를 쓴다. reviewer, linter, fidelity는 특히.
- 한 Phase/기능이 끝나면 pytest와 프론트 빌드를 통과시킨 뒤 커밋하고 `docs/PROGRESS.md`를 갱신한다.
- 프롬프트(`app/prompts/*.md`)나 검수 규칙(`app/data/reviewer_rules.yaml`, `engine/reviewer.py`)을 바꾸면 질문 품질 평가를 돌려 PROGRESS.md 표에 기록한다. 기획안 목표: 질문 1개 98%, 직전 발화 이어받기 85%, 검수 1차 통과 80%.

## 명령어
```bash
# 백엔드 (uv, FastAPI, SQLAlchemy 2.x, Pydantic v2) — 진입점은 pyproject.toml [tool.fastapi]
cd backend && uv run fastapi dev                     # http://127.0.0.1:8000, /docs
cd backend && PYTHONUTF8=1 uv run pytest             # 오프라인 테스트 (가짜 LLM)
cd backend && PYTHONUTF8=1 uv run pytest tests/test_turns.py::test_turn_happy_path   # 하나만
cd backend && RUN_LIVE=1 PYTHONUTF8=1 uv run pytest tests/test_live.py -v -s        # 실제 API (비용)
cd backend && PYTHONUTF8=1 uv run python -m evals.eval_questions --label 메모        # 질문 품질 평가 (~$0.6) → experiments/eval/
cd backend && uv run python -m app.prompt_sync       # SKILL.md → prompts/core.md, stage*.md 재생성
cd backend && uv run ruff check .                    # 린트 (--fix 가능)
cd backend && uv add <패키지>

# 프론트 (Vite, React 19, TypeScript) — /api/* 는 127.0.0.1:8000 으로 프록시
cd frontend && npm run dev                           # http://localhost:5173
cd frontend && npm run build                         # tsc -b + vite build
cd frontend && npm run lint                          # oxlint
```

## 배포
- Vercel 프로젝트 `one-scene` (https://one-scene.vercel.app), GitHub `awesome72/one-scene`(공개)의 `main`에 푸시하면 production 자동 배포. PR·다른 브랜치는 preview.
- `vercel.json`의 Services: `frontend`(Vite, SPA 폴백)와 `backend`(FastAPI `app/main.py`). 공개 `/api/*`는 백엔드로 가고, 백엔드 쪽 rewrite가 `/api` 접두어를 떼므로 FastAPI 라우트에는 `/api`가 없다.
- 운영 DB는 `DATABASE_URL`(Neon, `postgres://`를 `config.sqlalchemy_url`이 psycopg 3 주소로 바꿈). 없으면 Vercel에서는 `/tmp` SQLite (유지 안 됨). 스키마는 `create_all`뿐이라 컬럼을 바꾸면 운영 DB도 직접 손봐야 한다 (Alembic 도입 전).
- 환경 변수는 `vercel env`로 관리 (`ANTHROPIC_API_KEY`, `MODEL_*`, `DAILY_LLM_LIMIT`). 로그인(B2) 전까지 공개 접속이므로 `DAILY_LLM_LIMIT`(하루 전체 AI 작업 상한, 기본 300)이 비용 안전장치다.
- CLI 배포(`vercel deploy`)는 로컬 파일을 올린다. 비밀·개인 글은 `.vercelignore`로 막는다. Windows Git Bash의 curl은 한글 JSON 본문을 깨뜨리므로 운영 API 확인은 httpx로 한다.

## 아키텍처

### 백엔드 계층
`routers/` (sessions, turns, drafts, library) → `engine/` → `models.py`.
- **LLM 호출은 `engine/` 안에서만.** 엔진은 `engine/llm.py`의 `LLM` 프로토콜(`text`, `parse`)에만 의존한다. 라우터는 `Depends(get_llm)`으로 받고, 테스트는 이를 `tests/fakes.py`의 `FakeLLM`으로 바꾼다 (`fake.queue(<pydantic 응답>)`, `fake.extractions`, `fake.questions`, `fake.reviews`).
- `AnthropicLLM`은 `client.beta.messages`를 쓰고 `FALLBACK_MODELS`에는 `fallbacks="default"`를 붙인다. 구조화 출력은 `beta.messages.parse(output_format=PydanticModel)`. 호출별 토큰 사용량을 `self.usage`에 쌓는다 (평가 비용 계산용).
- 모델 이름은 `.env`의 `MODEL_QUESTIONER/ASSEMBLER/FIDELITY`(Sonnet 5.5), `MODEL_EXTRACTOR/REVIEWER`(Haiku 4.5)를 `config.py`로만 참조한다. Haiku에는 `effort`를 보내지 않는다.
- ORM → 응답 변환은 `views.py`, 스키마는 `schemas.py`(세션·턴·재료)와 `schemas_draft.py`(개요·초안·교정). SQLite가 시간대를 잃으므로 시각 필드는 `UtcDatetime`.
- 인증은 임시다: `X-User-Id` 헤더(없으면 `dev-user`), 프론트는 localStorage에 ID를 만든다 (open-questions B2). 세션 접근은 `deps.OwnedSessionDep`가 소유자를 확인한다.

### 한 턴 처리 (`engine/pipeline.py`, `POST /sessions/{id}/turns` SSE)
1. 사용자 턴 저장 → `extractor`(Haiku). `keep_verbatim`이 원문에 없는 조각을 버리고(공백·따옴표 차이만 허용, `find_verbatim`), `ensure_dialogue`가 놓친 따옴표 대사를 원문 그대로 더한다.
2. `apply_extraction`: 재료(`seq`, 프롬프트에서는 `m{seq}`), 신호(`repeated`는 사용자 발화 전체에서 매번 다시 셈, `gap`, `skipped`, `hesitation`). 주제 문장·목표 길이는 비어 있을 때만 채운다 (이후는 사용자가 PATCH).
3. `distress`면 질문 대신 `data/fixed_replies.yaml` 고정 응답. 단계 마감 조건(`stage_machine.missing`)이 처음 채워지면 `card` 이벤트를 단계당 한 번(`card_offered_stage`).
4. `questioner` ⇄ `reviewer` 최대 3회. reviewer는 먼저 `rule_check`(물음표 1개, 두 질문 잇기, 문장 수, 상투어, 인용이 사용자 원문인지, 직전 질문 되풀이)를 돌리고, 걸리면 LLM을 부르지 않는다. 탈락 사유는 `questioner_feedback.md`로 다음 시도에 들어간다. 3회 모두 탈락해도 마지막 시도를 보낸다. 시도 기록은 코치 턴의 `meta.attempts`.
- SSE 이벤트: `status(extracting|asking|reviewing)` → `materials` → `card`? → `question` | `error`. 검수를 통과하기 전의 질문은 보내지 않는다. `POST /sessions/{id}/coach`는 사용자 발화 없이 새 단계의 여는 질문을 만들고, `TurnCreate.skip=true`는 추출 없이 직전 질문을 넘어간 주제로 기록한다.
- 프롬프트 조립(`prompt_builder.py`): system = [core + 단계 모듈 + questioner.md (cache_control)] + [세션 상태 YAML, 매 턴 바뀜]. **messages는 user로 시작하고 user로 끝나야 한다** (Sonnet 5.5는 prefill 불가). 코치 턴이 연달아 있으면 사이에 `stage_opened.md`를, 맨 앞에는 `session_start.md`를 끼운다.

### 개요·초안·교정 (`engine/drafting.py`)
- `outline.plan`: 패턴 4개(linear/return/frame/cross) × 재료 → 단락 순서·분량(SKILL.md 6장 비율). LLM 없이 결정적. `arc_block`이 없는 재료는 개요에 들어가지 않는다.
- `handle_draft`(SSE `status(assembling|checking)` → `draft`): **조립 전에 저장된 패턴으로 개요를 다시 계산한다** (교정 답으로 생긴 재료 반영). `assembler`(재료 번호로 출처 표시) → `fidelity.structural`(출처 없음·없는 재료 → 빈칸) → `fidelity.semantic`(재료 + 그 재료가 나온 사용자 발화 대비) → `cliche_linter`.
- 초안의 원천은 `drafts.sentence_map`(`paragraph, text, material_ids, is_blank, note`)이고 `body`는 파생값. 교정 표시 id는 `"{문장}:{시작}:{종류}"`, `lint_result[].dismissed`가 '그대로 두기'(B5). 교정 질문에 답하면 질문·답이 대화 턴으로 남고 답에서 재료를 뽑는다 (초안에는 '다시 만들기' 때 반영).
- 태그는 Haiku가 제안만 하고 사용자가 `PUT /tags`로 저장한다. 보관함의 다음 글감 = `gap` 태그 중 아직 새 글 첫 질문으로 쓰지 않은 것.

### 프롬프트와 데이터 (`backend/app/prompts`, `backend/app/data`)
- `core.md`, `stage1_topic.md` ~ `stage4_revise.md`는 **SKILL.md에서 자동 생성**된다. 직접 고치지 말고 SKILL.md를 고친 뒤 `app.prompt_sync`를 실행한다. `tests/test_prompt_sync.py`가 동기화와 원문 보존을 검사한다.
- 나머지(`questioner`, `extractor`, `reviewer`, `assembler`, `fidelity`, `tagger`, `questioner_feedback`, `session_start`, `stage_opened`)는 직접 쓴 파일이다. 코드 안에 프롬프트 문자열을 두지 않는다. 평가 채점자 프롬프트만 `backend/evals/judge.md`.
- `data/cliches.yaml`은 SKILL.md 7장 사전(`examples`·`source`를 테스트가 검사). 그 밖에 `reviewer_rules.yaml`, `fixed_replies.yaml`, `opening_questions.yaml`.

### 테스트
- `tests/conftest.py`: 메모리 SQLite + `get_db` 오버라이드. TestClient를 컨텍스트 매니저로 열지 않는다 (lifespan이 실제 DB 파일을 만들지 않게).
- `tests/golden/quit_job.yaml`(SKILL.md 10장 예시), `tests/golden/scenarios.yaml`(평가용 10개). `test_live.py`는 `RUN_LIVE=1`일 때만 돈다.

### 프론트엔드 (`frontend/src`)
- 해시 라우팅(`lib/route.ts`): `#/`, `#/library`, `#/s/{id}`(대화), `#/s/{id}/outline`, `/draft`, `/finish`.
- `api/client.ts`가 모든 API 호출과 타입을 가진다. POST SSE는 EventSource 대신 fetch 스트림을 직접 파싱한다. 상태의 원천은 서버다.
- 음성: `lib/speech.ts`(받아쓰기)와 `lib/tts.ts`(읽어 주기)는 브라우저 Web Speech API 임시 구현이다. 서버 STT/TTS(Phase 5)로 바꿀 때는 이 두 파일만 교체한다. 마이크를 켜기 전에 `stopSpeaking()`.
- 모바일 우선(최대 430px). 디자인 토큰은 `index.css`의 CSS 변수(design-spec.md 2절). 사람의 말·글은 세리프(`--serif`), UI는 산세리프. 조사는 `lib/josa.ts`로 받침에 맞춘다. 문구는 목업 말투(존댓말, 짧게, 평가·칭찬 없음).

## 이 환경(Windows)에서 겪은 함정
- `uv run fastapi dev`의 자동 재시작이 가끔 이전 코드로 남는다. 백엔드를 고친 뒤 동작이 이상하면 서버를 직접 재시작한다.
- 개발 DB(`backend/one_scene.db`)는 마이그레이션이 없다(`create_all`). 모델 컬럼을 바꾸면 지우고 다시 만든다.
- 한글 출력은 `PYTHONUTF8=1`. 단 `python -I`는 이 환경 변수를 무시하므로 그때는 `-X utf8`.
- Bash 도구의 heredoc에 따옴표가 섞인 긴 Python/TS 코드를 넣으면 셸 파싱이 실패할 수 있다. 파일 수정은 Edit/Write 도구로 한다.
- 최신 Chromium의 `scrollIntoView()`는 Promise를 돌려준다. `useEffect` 화살표 함수에서 그대로 반환하면 React가 정리 함수로 호출하다 화면이 멈춘다. 중괄호로 감싼다.
- `글모음/`은 사용자의 개인 글이다. 커밋하지 않는다 (`git add -A -- . ':!글모음'`).
