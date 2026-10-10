import { ARC_BLOCKS, ARC_SHORT, type ArcBlock } from '../api/client'

// 서사 아크 곡선 (기획안 홈·대화): 장면에서 올라가 의미에서 정점, 여운으로 내려온다.
// 블록마다 재료 개수, 아직 필요한 블록에는 점선 고리
const POINTS: Record<ArcBlock, [number, number]> = {
  scene: [24, 70],
  event: [87, 40],
  meaning: [150, 24],
  present: [213, 40],
  resonance: [276, 70],
}

export function ArcCurve({
  arc,
  next,
  onClick,
}: {
  arc: Record<ArcBlock, number>
  next?: ArcBlock | null
  onClick?: () => void
}) {
  const label = ARC_BLOCKS.map((b) => `${ARC_SHORT[b]} ${arc[b]}`).join(', ')
  const svg = (
    <svg viewBox="0 0 300 92" className="arc-curve" role="img" aria-label={`서사 아크: ${label}`}>
      <path className="curve" d="M24 70 C 70 70, 95 24, 150 24 S 230 70, 276 70" />
      {ARC_BLOCKS.map((b) => {
        const [x, y] = POINTS[b]
        const top = y < 50
        return (
          <g key={b} className={`${arc[b] > 0 ? 'filled' : ''} ${b === next ? 'next' : ''}`}>
            {b === next && <circle className="ring" cx={x} cy={y} r={11} />}
            <circle className="node" cx={x} cy={y} r={7} />
            <text x={x} y={top ? y - 14 : y + 20} textAnchor="middle">
              {ARC_SHORT[b]} {arc[b]}
            </text>
          </g>
        )
      })}
    </svg>
  )
  return onClick ? (
    <button type="button" className="arc-button" onClick={onClick} aria-label={`${label}. 마감 조건 보기`}>
      {svg}
    </button>
  ) : (
    svg
  )
}
