import { useEffect, useState } from 'react'
import { api, type Library as LibraryData } from '../api/client'
import { DeleteButton } from '../components/DeleteButton'
import { go } from '../lib/route'

const KIND_LABEL = { period: '시기', person: '인물', place: '장소', object: '핵심 사물' } as const

// 보관함 (목업 ⑦): 완성한 글 + 다음 글감
export function Library() {
  const [data, setData] = useState<LibraryData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.library().then(setData).catch((e) => setError(String(e.message ?? e)))
  }, [])

  const reload = async () => setData(await api.library())

  const startFrom = async (question: string) => {
    setBusy(true)
    try {
      const s = await api.createSession(question)
      go({ name: 'chat', id: s.id })
    } catch (e) {
      setError(String((e as Error).message))
      setBusy(false)
    }
  }

  return (
    <div className="page library">
      <header className="top row between">
        <button type="button" className="link" onClick={() => go({ name: 'home' })}>
          ← 홈
        </button>
        <h1 className="logo">보관함</h1>
        <span />
      </header>
      {error && <p className="error">{error}</p>}
      {!data ? (
        <p className="hint">불러오는 중…</p>
      ) : (
        <>
          <p className="eyebrow">완성한 글 {data.done.length}편</p>
          {data.done.length === 0 && <p className="hint">아직 완성한 글이 없어요.</p>}
          {data.done.map((d) => (
            <section key={d.id} className="panel">
            <button type="button" className="essay" onClick={() => go({ name: 'draft', id: d.id })}>
              <p className="eyebrow">
                {new Date(d.finished_at).toLocaleDateString('ko-KR', { month: 'long', day: 'numeric' })} 완성 ·{' '}
                {d.paragraphs}단락, {d.chars.toLocaleString('ko-KR')}자
              </p>
              <h2 className="title">{d.title}</h2>
              {d.first_sentence && <p className="said small">{d.first_sentence}</p>}
              <dl className="tags">
                {(Object.keys(KIND_LABEL) as (keyof typeof KIND_LABEL)[])
                  .filter((k) => d.tags[k].length)
                  .map((k) => (
                    <div key={k}>
                      <dt>{KIND_LABEL[k]}</dt>
                      <dd>{d.tags[k].join(', ')}</dd>
                    </div>
                  ))}
              </dl>
            </button>
              <DeleteButton
                label="이 글 지우기"
                confirmLabel="대화·재료·초안까지 모두 지워져요."
                onDelete={async () => {
                  await api.deleteSession(d.id)
                  await reload()
                }}
              />
            </section>
          ))}

          {data.next_topics.length > 0 && (
            <section className="panel">
              <p className="eyebrow">다음 글감</p>
              <p className="sub">대화에서 나왔지만 아직 쓰지 않은 장면이에요</p>
              {data.next_topics.map((t) => (
                <button
                  type="button"
                  key={t.question}
                  className="topic"
                  disabled={busy}
                  onClick={() => startFrom(t.question)}
                >
                  <span className="question small">{t.question}</span>
                  <span className="sub">‘{t.from_title}’에서 나온 질문</span>
                </button>
              ))}
            </section>
          )}

          <section className="danger-zone">
            <DeleteButton
              label="내 글 모두 지우기"
              confirmLabel="쓰는 중인 글까지 모두 지워지고 되돌릴 수 없어요."
              onDelete={async () => {
                await api.deleteMyData()
                await reload()
              }}
            />
          </section>
        </>
      )}
    </div>
  )
}
