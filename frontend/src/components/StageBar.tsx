import { STAGE_NAMES } from '../api/client'

// 4단계 진행 바: 지금 어디에 있는지 늘 보인다
export function StageBar({ stage }: { stage: number }) {
  return (
    <div className="stage-bar" aria-label={`${stage}단계 ${STAGE_NAMES[stage]}`}>
      <ol>
        {[1, 2, 3, 4].map((n) => (
          <li key={n} className={n < stage ? 'done' : n === stage ? 'current' : ''} />
        ))}
      </ol>
      <span>
        {stage}단계 {STAGE_NAMES[stage]}
      </span>
    </div>
  )
}
