import { ARC_SHORT, type ArcBlock, type Material } from '../api/client'

// 코치 질문 안의 인용: ‘…’, '…', "…", “…” (Quoted와 같은 규칙)
const QUOTE = /[‘'"“]([^‘'"“”’]{1,40})[’'"”]/g

// 내 대답 하나 (진행 신호 3층): 다음 질문이 이어받은 구절에 밑줄, 아래에는 방금 생긴 재료
export function Answer({
  text,
  next,
  added,
  mine = false,
}: {
  text: string
  next?: string
  added?: Material[]
  mine?: boolean
}) {
  const quotes = next ? [...next.matchAll(QUOTE)].map((m) => m[1].trim()).filter((q) => text.includes(q)) : []
  const parts: (string | { u: string })[] = []
  if (quotes.length) {
    const pattern = new RegExp(`(${quotes.map((q) => q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`)
    for (const piece of text.split(pattern)) {
      if (piece) parts.push(quotes.includes(piece) ? { u: piece } : piece)
    }
  } else {
    parts.push(text)
  }
  const blocks = [...new Set((added ?? []).map((m) => m.arc_block).filter((b): b is ArcBlock => b !== null))]
  return (
    <div className={`answer ${mine ? 'mine' : ''}`}>
      <p className="past user">
        {parts.map((p, i) => (typeof p === 'string' ? p : <u key={i}>{p.u}</u>))}
      </p>
      {added && added.length > 0 && (
        <p className="receipt">
          ✓ 재료 {added.length}개
          {blocks.map((b) => (
            <span key={b} className="chip ok">
              {ARC_SHORT[b]}
            </span>
          ))}
        </p>
      )}
    </div>
  )
}
