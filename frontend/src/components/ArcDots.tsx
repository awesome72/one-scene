import { ARC_BLOCKS, ARC_SHORT, type ArcBlock } from '../api/client'

// 서사 아크 5블록 채움 상태 (목업 홈·대화 헤더)
export function ArcDots({ arc, onClick }: { arc: Record<ArcBlock, number>; onClick?: () => void }) {
  const body = ARC_BLOCKS.map((b) => (
    <span key={b} className={`arc-dot ${arc[b] > 0 ? 'filled' : ''}`} title={`${ARC_SHORT[b]} ${arc[b]}개`}>
      <i />
      {ARC_SHORT[b]}
    </span>
  ))
  return onClick ? (
    <button type="button" className="arc-dots" onClick={onClick} aria-label="재료 카드 보기">
      {body}
    </button>
  ) : (
    <div className="arc-dots">{body}</div>
  )
}
