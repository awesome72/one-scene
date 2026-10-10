import { useEffect, useState } from 'react'
import { api, type Outline as OutlineData, type PatternId, type SessionDetail } from '../api/client'
import { Journey } from '../components/Journey'
import { josa } from '../lib/josa'
import { go } from '../lib/route'

const STEP_TEXT = { assembling: '초안을 짜고 있어요', checking: '문장마다 출처를 확인하고 있어요' } as const

// 계열 짜기 (목업 ⑤): 패턴을 고르면 단락 개요가 바뀐다. 결정은 사용자가 한다
export function Outline({ id }: { id: string }) {
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [outline, setOutline] = useState<OutlineData | null>(null)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.getSession(id), api.outline(id)])
      .then(([s, o]) => {
        setSession(s)
        setOutline(o)
      })
      .catch((e) => setError(String(e.message ?? e)))
  }, [id])

  const pick = async (pattern: PatternId) => {
    setOutline(await api.outline(id, pattern))
  }

  const makeDraft = async () => {
    if (!outline?.pattern || !session) return
    setError(null)
    try {
      await api.saveOutline(id, outline.pattern)
      // 이 버튼이 사용자의 단계 이동 승인이다 (CLAUDE.md 제품 규칙 4)
      if (session.stage === 3) setSession(await api.advance(id))
      setStatus(STEP_TEXT.assembling)
      let ok = false
      await api.makeDraft(id, (e) => {
        if (e.event === 'status') setStatus(STEP_TEXT[e.data.step])
        if (e.event === 'error') setError(e.data.message)
        if (e.event === 'draft') ok = true
      })
      if (ok) go({ name: 'draft', id })
    } catch (e) {
      setError(String((e as Error).message))
    } finally {
      setStatus(null)
    }
  }

  if (!session || !outline) {
    return <div className="page">{error ? <p className="error">{error}</p> : <p className="hint">불러오는 중…</p>}</div>
  }

  return (
    <div className="page outline">
      <header className="chat-head">
        <button type="button" className="link" onClick={() => go({ name: 'chat', id })}>
          ← 대화
        </button>
        <h1 className="title">{session.title || session.topic_sentence || '새 글'}</h1>
        <Journey stage={session.stage} progress={session.progress} />
      </header>

      <p className="question">모은 장면을 어떤 순서로 놓을까요?</p>
      {outline.bookends.length > 0 && (
        <p className="note">
          {josa(outline.bookends.map((w) => `‘${w}’`).join(', '), '이', '가')} 첫 장면과 마지막 장면에 모두 있어요.
        </p>
      )}

      <div className="patterns" role="radiogroup" aria-label="계열 패턴">
        {outline.patterns.map((p) => (
          <button
            type="button"
            key={p.id}
            role="radio"
            aria-checked={p.id === outline.pattern}
            className={`pattern ${p.id === outline.pattern ? 'on' : ''}`}
            onClick={() => pick(p.id)}
          >
            <strong>{p.name}</strong>
            <span>{p.desc}</span>
          </button>
        ))}
      </div>

      <section className="panel">
        <p className="eyebrow">
          단락 개요 · {outline.items.length}단락, 약 {outline.total_chars.toLocaleString('ko-KR')}자
        </p>
        <ol className="outline-list">
          {outline.items.map((item) => (
            <li key={item.position}>
              <span className="num">{item.position}</span>
              <div>
                <p className="block-label">
                  {item.label} <span>약 {item.target_chars}자</span>
                </p>
                {item.materials.length ? (
                  item.materials.map((m) => (
                    <p key={m.id} className="said small">
                      “{m.text}”
                    </p>
                  ))
                ) : (
                  <p className="hint">재료가 없어요. 초안에서 빈칸으로 남겨요.</p>
                )}
              </div>
            </li>
          ))}
        </ol>
      </section>

      {status && (
        <p className="status" role="status">
          <span className="pulse" /> {status}
        </p>
      )}
      {error && <p className="error">{error}</p>}

      <footer className="composer">
        <button type="button" className="primary wide" disabled={status !== null} onClick={makeDraft}>
          이 순서로 초안 만들기
        </button>
        <p className="hint center">초안을 만든 뒤에도 순서는 바꿀 수 있어요</p>
      </footer>
    </div>
  )
}
