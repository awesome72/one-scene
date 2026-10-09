// 코치 질문 안의 인용(사용자 말)을 강조한다: ‘…’, '…', "…", “…”
const QUOTE = /([‘'"“])([^‘'"“”’]{1,40})([’'"”])/g

export function Quoted({ text }: { text: string }) {
  const parts: (string | { q: string })[] = []
  let last = 0
  for (const m of text.matchAll(QUOTE)) {
    if (m.index! > last) parts.push(text.slice(last, m.index))
    parts.push({ q: `‘${m[2]}’` })
    last = m.index! + m[0].length
  }
  if (last < text.length) parts.push(text.slice(last))
  return (
    <>
      {parts.map((p, i) => (typeof p === 'string' ? p : <em key={i}>{p.q}</em>))}
    </>
  )
}
