# 한 장면 (One Scene) — 프로젝트 규칙

## 이 서비스가 무엇인가
AI가 글을 대신 쓰지 않고, 한 번에 하나씩 질문해 사용자의 기억 속 장면을 끌어내는
대화형 글쓰기 서비스. 대화 원칙의 원본은 .claude/skills/scene-essay-coach/SKILL.md.
제품 동작을 바꾸는 코드를 쓸 때는 반드시 이 스킬 문서를 먼저 읽는다.

## 문서 지도
| 문서 | 내용 | 언제 읽나 |
|---|---|---|
| `.claude/skills/scene-essay-coach/SKILL.md` | 대화 원칙 원본 (철칙, 4단계, 서사 아크, 상투어 목록) | 프롬프트·엔진·교정 작업 전 |
| `docs/service-plan.md` | 기획안 (타깃, 기능 F1~F13, 지표, 수익 모델, 로드맵) | 기능 범위 판단 시 |
| `docs/claude-code-guide.md` | 구현 설계서 (스택, 구조, DB, API, 파이프라인, Phase 0~8 프롬프트) | 각 Phase 시작 전 |
| `docs/design/design-spec.md` | 목업에서 추출한 화면·디자인 토큰·문구 | 프론트엔드 작업 전 |
| `docs/design/mockup.html` | 7개 화면 모바일 목업 원본 (브라우저로 열기) | 화면 확인 시 |
| `docs/presentation.html` | 기획 발표 자료 | 참고용 |
| `docs/open-questions.md` | 문서 간 불일치·미정 사항 | 해당 Phase 착수 전 |
| `docs/PROGRESS.md` | 단계별 진행 체크리스트 (현재 위치) | 매 세션 시작 시 |

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
- core.md·stage*.md는 SKILL.md에서 자동 생성된다. 직접 고치지 말고 SKILL.md를 고친 뒤 `uv run python -m app.prompt_sync`
- LLM 호출은 engine/ 안에서만. 라우터에서 직접 호출 금지
- 프론트: React + TypeScript, 상태는 서버가 원천
- UI는 모바일 우선 (목업 기준 390×844). 디자인 토큰은 docs/design/design-spec.md를 따른다
- 사용자에게 보이는 문구는 목업의 말투를 따른다 (존댓말, 짧게, 평가·칭찬 없음)

## 작업 방식
- 새 기능 전에 계획을 먼저 보여주고 승인을 받는다
- 기능마다 테스트를 쓴다. 특히 reviewer, linter, fidelity는 테스트 필수
- 한 Phase가 끝나면 pytest와 프론트 빌드를 모두 통과시킨 뒤 커밋
- Phase를 마치면 docs/PROGRESS.md 체크리스트를 갱신한다

## 명령어
- 백엔드 실행: cd backend && uv run fastapi dev   (http://127.0.0.1:8000, 문서 /docs)
- 테스트: cd backend && PYTHONUTF8=1 uv run pytest   (Windows 콘솔 한글 깨짐 방지)
- 실제 API 테스트(비용 발생): cd backend && RUN_LIVE=1 PYTHONUTF8=1 uv run pytest tests/test_live.py -v -s
- 린트: cd backend && uv run ruff check .
- 패키지 추가: cd backend && uv add <패키지>
- 프론트: cd frontend && npm run dev   (/api/* 요청은 백엔드로 프록시)
- 프론트 빌드: cd frontend && npm run build
