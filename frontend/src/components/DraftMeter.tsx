import type { Draft, SessionDetail } from '../api/client'

// 초안 완성 미터 (진행 신호, 4단계): 문장마다 내 말 / 내가 고친 문장 / AI 제안 / 빈칸. 평가 없이 개수만
export function DraftMeter({
  draft,
  session,
  onFirstBlank,
}: {
  draft: Draft
  session: SessionDetail
  onFirstBlank?: () => void
}) {
  const sentences = draft.paragraphs.flatMap((p) => p.sentences)
  const kept = new Set(draft.hits.filter((h) => h.kind === 'blank' && h.dismissed).map((h) => h.sentence))
  const own = sentences.filter((s) => !s.is_blank && !s.edited).length
  const edited = sentences.filter((s) => !s.is_blank && s.edited).length
  const suggested = sentences.filter((s) => s.is_blank && s.suggestion && !kept.has(s.index)).length
  const blank = sentences.filter((s) => s.is_blank && !s.suggestion && !kept.has(s.index)).length
  const marks = draft.hits.filter((h) => !h.dismissed && h.kind !== 'blank').length
  const tagsDone = session.progress.conditions.find((c) => c.key === 'tags')?.done ?? false
  const segments = [
    { key: 'own', n: own, label: `내 말 ${own}문장` },
    { key: 'edited', n: edited, label: `직접 고친 ${edited}` },
    { key: 'suggested', n: suggested, label: `AI 제안 ${suggested}` },
    { key: 'blank', n: blank, label: `빈칸 ${blank}` },
  ]
  const left = suggested + blank
  return (
    <section className="draft-meter" aria-label="완성까지 남은 일">
      <p className="row between">
        <b>{left ? `완성까지 채울 자리 ${left}곳` : '채울 자리가 없어요'}</b>
        {left > 0 && onFirstBlank && (
          <button type="button" className="link" onClick={onFirstBlank}>
            빈칸부터 채우기
          </button>
        )}
      </p>
      <div className="meter-bar" aria-hidden>
        {segments
          .filter((s) => s.n > 0)
          .map((s) => (
            <i key={s.key} className={s.key} style={{ flex: s.n }} />
          ))}
      </div>
      <p className="meter-legend">
        {segments
          .filter((s) => s.n > 0)
          .map((s) => (
            <span key={s.key} className={s.key}>
              {s.label}
            </span>
          ))}
        <span className="plain">교정 표시 {marks}곳</span>
        <span className="plain">{tagsDone ? '태그 저장됨' : '태그 저장 전'}</span>
      </p>
    </section>
  )
}
