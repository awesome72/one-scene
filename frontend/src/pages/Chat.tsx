import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type SessionDetail, type Turn, type TurnEvent } from '../api/client'
import { ArcDots } from '../components/ArcDots'
import { ListenButton } from '../components/ListenButton'
import { MaterialCard } from '../components/MaterialCard'
import { Quoted } from '../components/Quoted'
import { StageBar } from '../components/StageBar'
import { VoiceSheet } from '../components/VoiceSheet'
import { go } from '../lib/route'
import { voiceSupported } from '../lib/speech'
import { speak, stopSpeaking, ttsSupported, useReadAloud, useStopSpeakingOnUnmount } from '../lib/tts'

const STEP_TEXT = {
  extracting: '말씀을 받아 적고 있어요',
  asking: '다음 질문을 고르고 있어요',
  reviewing: '질문을 다듬고 있어요',
} as const

const SKIP_TEXT = '이 질문은 넘어갈게요.'

// 대화 (목업 ②): 지금 질문 하나를 크게, 지난 대화는 흐리게, 넘어가기는 늘 보이게
export function Chat({ id }: { id: string }) {
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'idle' | 'typing' | 'voice'>('idle')
  const [draft, setDraft] = useState('')
  const [cardOpen, setCardOpen] = useState(false)
  const historyEnd = useRef<HTMLDivElement>(null)
  const [readAloud, setReadAloud] = useReadAloud()
  // onEvent 안에서 최신 값을 읽기 위한 ref
  const readAloudRef = useRef(readAloud)
  const lastInputRef = useRef<'voice' | 'text'>('text')
  useEffect(() => {
    readAloudRef.current = readAloud
  }, [readAloud])
  useStopSpeakingOnUnmount()

  useEffect(() => {
    Promise.all([api.getSession(id), api.turns(id)])
      .then(([s, t]) => {
        setSession(s)
        setTurns(t)
      })
      .catch((e) => setError(String(e.message ?? e)))
  }, [id])

  useEffect(() => {
    // 최신 Chromium의 scrollIntoView는 Promise를 돌려준다. effect가 그걸 반환하면 안 된다
    void historyEnd.current?.scrollIntoView({ block: 'end' })
  }, [turns.length])

  const onEvent = useCallback((e: TurnEvent) => {
    switch (e.event) {
      case 'status':
        setStatus(STEP_TEXT[e.data.step])
        break
      case 'materials':
        setSession(e.data.session)
        break
      case 'card':
        setCardOpen(true)
        break
      case 'question':
        setTurns((t) => [...t, e.data.turn])
        setStatus(null)
        if (readAloudRef.current) {
          // 말로 답하던 중이면, 다 읽은 뒤 바로 말하기 화면을 연다 (손 안 쓰는 대화)
          const handsFree = lastInputRef.current === 'voice' && voiceSupported()
          speak(e.data.turn.text, handsFree ? () => setMode('voice') : undefined)
        }
        break
      case 'error':
        setError(e.data.message)
        setStatus(null)
        break
    }
  }, [])

  const busy = status !== null

  const send = async (text: string, input_mode: 'voice' | 'text', skip = false) => {
    if (!text.trim() || busy) return
    setError(null)
    setMode('idle')
    setDraft('')
    lastInputRef.current = input_mode
    const optimistic: Turn = {
      id: `local-${Date.now()}`,
      idx: turns.length,
      role: 'user',
      text,
      input_mode,
      stage: session?.stage ?? 1,
      created_at: new Date().toISOString(),
    }
    setTurns((t) => [...t, optimistic])
    setStatus(skip ? STEP_TEXT.asking : STEP_TEXT.extracting)
    try {
      await api.sendTurn(id, { text, input_mode, skip }, onEvent)
    } catch (e) {
      setError(String((e as Error).message))
    } finally {
      setStatus(null)
    }
  }

  const moveStage = async (direction: 'advance' | 'back') => {
    setCardOpen(false)
    setError(null)
    try {
      const s = direction === 'advance' ? await api.advance(id) : await api.back(id)
      setSession(s)
      setStatus(STEP_TEXT.asking)
      await api.openStage(id, onEvent)
    } catch (e) {
      setError(String((e as Error).message))
    } finally {
      setStatus(null)
    }
  }

  if (!session) {
    return <div className="page">{error ? <p className="error">{error}</p> : <p className="hint">불러오는 중…</p>}</div>
  }

  const lastCoach = [...turns].reverse().find((t) => t.role === 'coach')
  const past = lastCoach ? turns.slice(0, turns.indexOf(lastCoach)) : turns
  const after = lastCoach ? turns.slice(turns.indexOf(lastCoach) + 1) : []

  return (
    <div className="page chat">
      <header className="chat-head">
        <div className="row between">
          <button type="button" className="link" onClick={() => go({ name: 'home' })}>
            ← 홈
          </button>
          <div className="row">
            {ttsSupported() && (
              <button
                type="button"
                className={`chip ${readAloud ? 'on' : ''}`}
                aria-pressed={readAloud}
                onClick={() => setReadAloud(!readAloud)}
              >
                읽어 주기 {readAloud ? '켬' : '끔'}
              </button>
            )}
            <button type="button" className="chip" onClick={() => setCardOpen(true)}>
              재료 {session.material_count}
            </button>
          </div>
        </div>
        <h1 className="title">{session.title || session.topic_sentence || '새 글'}</h1>
        <StageBar stage={session.stage} />
        <ArcDots arc={session.arc} onClick={() => setCardOpen(true)} />
        {session.repeated.length > 0 && (
          <p className="repeated">
            반복된 말 {session.repeated.map((r) => `${r.value} ${r.count}회`).join(' · ')}
          </p>
        )}
      </header>

      <div className="history" aria-label="지난 대화">
        {past.map((t) => (
          <p key={t.id} className={`past ${t.role}`}>
            {t.text}
          </p>
        ))}
      </div>

      {lastCoach && (
        <section className="now" aria-live="polite">
          <p className="eyebrow row between">
            지금 질문 <ListenButton key={lastCoach.id} text={lastCoach.text} />
          </p>
          <p className="question">
            <Quoted text={lastCoach.text} />
          </p>
        </section>
      )}
      {after.map((t) => (
        <p key={t.id} className="past user mine">
          {t.text}
        </p>
      ))}
      <div ref={historyEnd} />

      {status && (
        <p className="status" role="status">
          <span className="pulse" /> {status}
        </p>
      )}
      {error && <p className="error">{error}</p>}

      <footer className="composer">
        {session.stage >= 3 && mode === 'idle' && (
          <button
            type="button"
            className="secondary wide"
            onClick={() => go({ name: session.stage === 3 ? 'outline' : 'draft', id })}
          >
            {session.stage === 3 ? '단락 순서 정하기' : '초안 보기'}
          </button>
        )}
        {mode === 'typing' ? (
          <form
            onSubmit={(e) => {
              e.preventDefault()
              send(draft, 'text')
            }}
          >
            <textarea
              autoFocus
              rows={4}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="떠오르는 대로 적어 주세요"
              aria-label="답 쓰기"
            />
            <div className="row">
              <button type="button" className="secondary" onClick={() => setMode('idle')}>
                취소
              </button>
              <button type="submit" className="primary" disabled={busy || !draft.trim()}>
                보내기
              </button>
            </div>
          </form>
        ) : (
          <div className="row">
            {voiceSupported() && (
              <button
                type="button"
                className="primary grow"
                disabled={busy}
                onClick={() => {
                  stopSpeaking()
                  setMode('voice')
                }}
              >
                누르고 말하기
              </button>
            )}
            <button type="button" className="secondary grow" disabled={busy} onClick={() => setMode('typing')}>
              답 쓰기
            </button>
          </div>
        )}
        <button type="button" className="link skip" disabled={busy} onClick={() => send(SKIP_TEXT, 'text', true)}>
          이 질문은 넘어가기
        </button>
      </footer>

      {mode === 'voice' && lastCoach && (
        <VoiceSheet
          question={lastCoach.text}
          repeated={session.repeated.map((r) => r.value)}
          onClose={() => setMode('idle')}
          onSend={(text) => send(text, 'voice')}
        />
      )}
      {cardOpen && (
        <MaterialCard sessionId={id} onMore={() => setCardOpen(false)} onAdvance={() => moveStage('advance')} />
      )}
    </div>
  )
}
