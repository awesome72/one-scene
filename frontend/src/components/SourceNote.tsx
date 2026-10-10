import type { DraftSentence, Turn } from '../api/client'

// 문장별 출처: 그 문장의 재료가 나온 내 대답 원문, 재료 부분은 밑줄 ('지어내지 않는다'를 눈으로 확인)
export function SourceNote({ sentence, turns }: { sentence: DraftSentence; turns: Turn[] }) {
  if (sentence.accepted) return <span className="source">받아들인 AI 제안이에요.</span>
  if (sentence.edited) return <span className="source">직접 고친 문장이에요.</span>
  const users = turns.filter((t) => t.role === 'user')
  const byTurn = new Map<string, string[]>()
  for (const m of sentence.materials) byTurn.set(m.turn_id, [...(byTurn.get(m.turn_id) ?? []), m.text])
  return (
    <span className="source">
      {[...byTurn].map(([turnId, texts]) => {
        const turn = users.find((t) => t.id === turnId)
        if (!turn) return <span key={turnId}>“{texts.join(' · ')}”</span>
        const nth = users.filter((t) => t.stage === turn.stage).findIndex((t) => t.id === turnId) + 1
        return (
          <span key={turnId} className="source-turn">
            <small>
              {turn.stage}단계 {nth}번째 대답
            </small>
            <q>{underline(turn.text, texts)}</q>
          </span>
        )
      })}
    </span>
  )
}

function underline(text: string, parts: string[]): React.ReactNode[] {
  const ranges = parts
    .map((p) => [text.indexOf(p), p.length] as const)
    .filter(([i]) => i >= 0)
    .sort((a, b) => a[0] - b[0])
  const out: React.ReactNode[] = []
  let at = 0
  for (const [i, len] of ranges) {
    if (i < at) continue
    if (i > at) out.push(text.slice(at, i))
    out.push(<u key={i}>{text.slice(i, i + len)}</u>)
    at = i + len
  }
  if (at < text.length) out.push(text.slice(at))
  return out
}
