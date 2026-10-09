import { useEffect, useState } from 'react'
import { api, type SessionDetail } from '../api/client'
import { ArcDots } from '../components/ArcDots'
import { Quoted } from '../components/Quoted'
import { go } from '../lib/route'

// 홈 (목업 ①): 쓰는 중인 글 + 새 글을 여는 질문
export function Home() {
  const [current, setCurrent] = useState<SessionDetail[]>([])
  const [questions, setQuestions] = useState<string[]>([])
  const [qi, setQi] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.openingQuestions().then(setQuestions).catch(() => setQuestions([]))
    api
      .listSessions()
      .then((list) => Promise.all(list.filter((s) => s.status !== 'done').slice(0, 3).map((s) => api.getSession(s.id))))
      .then(setCurrent)
      .catch((e) => setError(String(e.message ?? e)))
  }, [])

  const start = async () => {
    setBusy(true)
    try {
      const s = await api.createSession(questions[qi])
      go({ name: 'chat', id: s.id })
    } catch (e) {
      setError(String((e as Error).message))
      setBusy(false)
    }
  }

  return (
    <div className="page home">
      <header className="top row between">
        <h1 className="logo">한 장면</h1>
        <button type="button" className="link" onClick={() => go({ name: 'library' })}>
          보관함
        </button>
      </header>

      {error && <p className="error">{error}</p>}

      {current.map((s) => (
        <section key={s.id} className="panel">
          <p className="eyebrow">쓰는 중인 글 · {s.stage}단계 {s.stage_name}</p>
          <h2 className="title">{s.title || s.topic_sentence || '제목 없는 글'}</h2>
          <ArcDots arc={s.arc} />
          {s.last_question && (
            <>
              <p className="eyebrow">마지막 질문</p>
              <p className="question small">
                <Quoted text={s.last_question} />
              </p>
            </>
          )}
          <button type="button" className="primary wide" onClick={() => go({ name: 'chat', id: s.id })}>
            이어서 답하기
          </button>
        </section>
      ))}

      <section className="panel">
        <p className="eyebrow">새 글을 여는 질문</p>
        <p className="question">{questions[qi] ?? '…'}</p>
        <div className="row">
          <button type="button" className="secondary" onClick={() => setQi((i) => (i + 1) % Math.max(questions.length, 1))}>
            다른 질문
          </button>
          <button type="button" className="primary" disabled={busy || !questions.length} onClick={start}>
            이 질문으로 새 글 시작
          </button>
        </div>
      </section>

      <p className="footnote">한 장면은 글을 대신 쓰지 않습니다. 당신이 한 말만으로 글을 짓습니다.</p>
    </div>
  )
}
