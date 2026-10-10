import { STAGE_NAMES, type SessionDetail } from '../api/client'
import { josa } from '../lib/josa'

// 단계 체크리스트 (진행 신호 2층): 이 단계를 마치는 조건과 대답 수. 이동은 사용자가 누를 때만
export function ProgressSheet({
  session,
  onClose,
  onAdvance,
  onCard,
}: {
  session: SessionDetail
  onClose: () => void
  onAdvance: () => void
  onCard: () => void
}) {
  const p = session.progress
  const [lo, hi] = p.expected_turns
  const max = Math.max(hi, p.turns_in_stage) * 1.15
  const pct = (n: number) => `${Math.min(100, (n / max) * 100)}%`
  const left = p.conditions.filter((c) => !c.done).length
  const next = session.stage < 4 ? STAGE_NAMES[session.stage + 1] : null

  return (
    <div className="sheet-backdrop" role="dialog" aria-label="단계 마감 조건" onClick={onClose}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <header className="sheet-head">
          <h2>
            {session.stage}단계 {STAGE_NAMES[session.stage]}
          </h2>
          <button type="button" className="link" onClick={onClose}>
            닫기
          </button>
        </header>
        <p className="lead">이 단계를 마치려면</p>
        <ul className="checklist">
          {p.conditions.map((c) => (
            <li key={c.key} className={c.done ? 'done' : ''}>
              <span className="box" aria-hidden>
                {c.done ? '✓' : ''}
              </span>
              <span>
                {c.label}
                {!c.done && c.hint && <small>{c.hint}</small>}
              </span>
              <em>{c.need > 1 || !c.done ? `${Math.min(c.have, c.need)} / ${c.need}` : c.have}</em>
            </li>
          ))}
        </ul>

        <div className="pace" aria-label={`이 단계의 대답 ${p.turns_in_stage}번, 보통 ${lo}~${hi}번`}>
          <div className="row between">
            <span>이 단계의 대답</span>
            <span>
              {p.turns_in_stage}번 · 보통 {lo}~{hi}번
            </span>
          </div>
          <div className="track">
            <i className="range" style={{ left: pct(lo), width: `calc(${pct(hi)} - ${pct(lo)})` }} />
            <i className="dot" style={{ left: pct(p.turns_in_stage) }} />
          </div>
        </div>

        {p.ready ? (
          <p className="hint">조건이 다 찼어요. 더 이야기해도 되고, 다음 단계로 넘어가도 돼요.</p>
        ) : (
          <p className="hint">남은 조건 {left}개. 다음 질문들이 이쪽을 향해요.</p>
        )}

        <div className="row">
          <button type="button" className="secondary grow" onClick={onClose}>
            조금 더 이야기하기
          </button>
          {p.ready && next && (
            <button type="button" className="primary grow" onClick={onAdvance}>
              {josa(next, '으로', '로')}
            </button>
          )}
        </div>
        <button type="button" className="link" onClick={onCard}>
          모은 재료 보기
        </button>
      </div>
    </div>
  )
}
