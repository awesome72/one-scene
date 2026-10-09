# 진행 체크리스트

> 매 세션 시작 시 여기서 현재 위치를 확인한다. Phase 프롬프트 원문은 `docs/claude-code-guide.md` 12장.
> 로드맵(기획안 13장): 1~2주 프롬프트 검증 → 3~6주 MVP(Phase 0~7) → 7~8주 베타 → 9~12주 v0.2

**현재 위치: Step 2 MVP 개발 진행 중 (Step 1 프롬프트 검증은 보류, 개발과 병행 가능)**

---

## Step 0. 작업 공간 준비 ✅ (2026-10-07)
- [x] 자료 정리: `docs/`(기획안·가이드·발표), `docs/design/`(목업), `.claude/skills/scene-essay-coach/SKILL.md`
- [x] `CLAUDE.md` 작성 (가이드 4장 템플릿 + 문서 지도·디자인 규칙)
- [x] 목업 분석 → `docs/design/design-spec.md`
- [x] 문서 간 불일치 정리 → `docs/open-questions.md`
- [x] `.gitignore`, `.env.example`, `git init`
- [x] 개발 도구 확인: Python 3.11.9, Node 24, npm 10, git, uv
- [x] `ANTHROPIC_API_KEY` 발급 후 `.env`에 넣기
- [x] 첫 커밋

## Step 1. 프롬프트 검증 (1~2주) — 코드 없이
목표: **질문만으로 글이 나오는가?** 자세한 방법은 `experiments/prompt-validation/README.md`
- [ ] 본인이 글 한 편을 4단계로 완주
- [ ] "어느 대답 뒤에 붙여도 되는 질문" 개수 세기 (첫 개선 지표)
- [ ] 지인 3명 테스트 + "내 이야기 같다" 5점 척도
- [ ] 대화 20건 수집 → `experiments/prompt-validation/logs/`
- [ ] 발견한 문제로 SKILL.md 수정 (수정 이력은 README에 기록)

## Step 2. MVP 개발 (3~6주)
각 Phase: 계획 확인 → 구현 → 테스트 통과 → 커밋 → 이 표 갱신

| Phase | 내용 | 착수 전 결정 (open-questions) | 상태 |
|---|---|---|---|
| 0 | 저장소 뼈대, FastAPI 헬스체크, Vite React TS | — | ✅ 2026-10-09 |
| 1 | 데이터 모델, 세션 API(`/sessions`, `/advance`, `/back`) | B2 사용자·인증 | ☐ |
| 2 | SKILL.md → `prompts/*.md`, `cliches.yaml` | — | ☐ |
| 3 | 대화 엔진(추출·질문·검수·단계 판정), SSE, golden 테스트 | B1, B3, B4 / API 키 | ☐ |
| — | **직접 글 한 편 완주 (가장 중요한 검증)** | | ☐ |
| 4 | 프론트 대화 화면 (StageBar, ArcPanel, MaterialCard, MicButton) | A1, A3 | ☐ |
| 5 | 음성 입력 (STT 어댑터, 확인 후 전송) | D1 STT 선정 | ☐ |
| 6 | 개요·초안·진실성·린터·교정 화면 | A2, B5, C1~C4 | ☐ |
| 7 | 태그와 보관함, 다음 글감 | — | ☐ |
| 8 | golden 시나리오 10개, `eval_questions.py` 지표 | D3 | ☐ |

## Step 3. 클로즈드 베타 (7~8주)
- [ ] 배포 (D2)
- [ ] 글쓰기 모임 2곳, 30명
- [ ] 1단계 → 완성률 35% 확인
