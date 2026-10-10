import { JOURNEY_STEPS, STAGE_NAMES, type Progress } from '../api/client'

// 여정 막대 (진행 신호 1층): 주제 → 단락 → 순서 → 교정 → 완성. 지금 칸은 단계 안 진행만큼 찬다
export function Journey({
  stage,
  progress,
  onClick,
}: {
  stage: number
  progress: Progress
  onClick?: () => void
}) {
  const label = `${stage}단계 ${STAGE_NAMES[stage]}, 남은 조건 ${progress.conditions.filter((c) => !c.done).length}개`
  const body = (
    <ol className="journey">
      {JOURNEY_STEPS.map((name, i) => {
        const fill = Math.max(0, Math.min(1, progress.journey - i))
        const state = fill >= 1 ? 'done' : i === Math.floor(progress.journey) ? 'current' : ''
        return (
          <li key={name} className={state}>
            <i style={{ '--fill': `${Math.round(fill * 100)}%` } as React.CSSProperties} />
            {name}
          </li>
        )
      })}
    </ol>
  )
  return onClick ? (
    <button type="button" className="journey-button" onClick={onClick} aria-label={`${label}. 마감 조건 보기`}>
      {body}
    </button>
  ) : (
    <div aria-label={label}>{body}</div>
  )
}
