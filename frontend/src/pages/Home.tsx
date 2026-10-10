import { useEffect, useState } from 'react'
import { api, type SessionDetail } from '../api/client'
import { Journey } from '../components/Journey'
import { Onboarding } from '../components/Onboarding'
import { applyLargeText, largeText, markOnboarded, onboarded } from '../lib/display'
import { Quoted } from '../components/Quoted'
import { type AuthUser, signOut } from '../lib/auth'
import { DeleteButton } from '../components/DeleteButton'
import { go } from '../lib/route'

// '3일 전'처럼 짧게 (홈 카드의 마지막으로 쓴 때)
function since(iso: string): string {
  const minutes = (Date.now() - new Date(iso).getTime()) / 60000
  if (minutes < 60) return '방금'
  if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}시간 전`
  return `${Math.floor(minutes / (60 * 24))}일 전`
}

// 홈 (목업 ①): 쓰는 중인 글 + 새 글을 여는 질문
export function Home({ user, onSignOut }: { user: AuthUser | null; onSignOut: () => void }) {
  const [current, setCurrent] = useState<SessionDetail[]>([])
  const [questions, setQuestions] = useState<string[]>([])
  const [qi, setQi] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showIntro, setShowIntro] = useState(() => !onboarded())
  const [large, setLarge] = useState(largeText)

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
        <div className="row">
          <button type="button" className="link" onClick={() => go({ name: 'library' })}>
            보관함
          </button>
          <button
            type="button"
            className="link"
            aria-pressed={large}
            onClick={() => {
              applyLargeText(!large)
              setLarge(!large)
            }}
          >
            {large ? '보통 글자' : '큰 글자'}
          </button>
          {user && (
            <button
              type="button"
              className="link"
              title={user.email}
              onClick={async () => {
                await signOut()
                onSignOut()
              }}
            >
              로그아웃
            </button>
          )}
        </div>
      </header>

      {error && <p className="error">{error}</p>}
      {showIntro && (
        <Onboarding
          onDone={() => {
            markOnboarded()
            setShowIntro(false)
          }}
        />
      )}

      {current.map((s) => (
        <section key={s.id} className="panel">
          <Journey stage={s.stage} progress={s.progress} />
          <p className="eyebrow">쓰는 중인 글 · {s.stage}단계 {s.stage_name}</p>
          <h2 className="title">{s.title || s.topic_sentence || '제목 없는 글'}</h2>
          {s.progress.next_need ? (
            <p className="need">
              <b>다음 할 일</b> {s.progress.next_need}
            </p>
          ) : (
            s.progress.ready && (
              <p className="need">
                <b>다음 할 일</b> 이 단계를 마칠 수 있어요
              </p>
            )
          )}
          {s.last_question && (
            <>
              <p className="eyebrow">마지막 질문</p>
              <p className="question small">
                <Quoted text={s.last_question} />
              </p>
            </>
          )}
          <p className="remain">
            <span>마지막으로 쓴 때 · {since(s.updated_at)}</span>
            <span>
              남은 대화 약 {s.progress.remaining_minutes[0]}~{s.progress.remaining_minutes[1]}분
            </span>
          </p>
          <button type="button" className="primary wide" onClick={() => go({ name: 'chat', id: s.id })}>
            이어서 답하기
          </button>
          <DeleteButton
            label="이 글 지우기"
            confirmLabel="대화와 재료까지 모두 지워져요."
            onDelete={async () => {
              await api.deleteSession(s.id)
              setCurrent((list) => list.filter((x) => x.id !== s.id))
            }}
          />
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

      <p className="footnote">
        <a href="#/privacy">개인정보 처리방침</a>
      </p>
      <p className="footnote">한 장면은 당신이 한 말로 글을 짓습니다. 빈 곳에 AI가 쓴 문장은 ‘AI 제안’으로 보여 드리고, 받아들인 것만 글이 됩니다.</p>
    </div>
  )
}
