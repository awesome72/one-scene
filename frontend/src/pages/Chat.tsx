import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Material, type SessionDetail, type Turn, type TurnEvent } from '../api/client'
import { Answer } from '../components/Answer'
import { ArcCurve } from '../components/ArcCurve'
import { Journey } from '../components/Journey'
import { ListenButton } from '../components/ListenButton'
import { MaterialCard } from '../components/MaterialCard'
import { Quoted } from '../components/Quoted'
import { ProgressSheet } from '../components/ProgressSheet'
import { Resume } from '../components/Resume'
import { StageTransition } from '../components/StageTransition'
import { VoiceSheet } from '../components/VoiceSheet'
import { loadDraft, saveDraft, withPeriod } from '../lib/draftStore'
import { go } from '../lib/route'
import { useVoiceInput } from '../lib/recorder'
import { speak, stopSpeaking, ttsSupported, useReadAloud, useStopSpeakingOnUnmount } from '../lib/tts'

const STEP_TEXT = {
  extracting: '말씀을 받아 적고 있어요',
  asking: '다음 질문을 고르고 있어요',
  reviewing: '질문을 다듬고 있어요',
} as const

const SKIP_TEXT = '이 질문은 넘어갈게요.'
const STUCK_TEXT = '잘 떠오르지 않아요.'

// 대화 (목업 ②): 지금 질문 하나를 크게, 지난 대화는 흐리게, 넘어가기는 늘 보이게
export function Chat({ id }: { id: string }) {
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 쓰다 만 답이 있으면 입력창을 열어 둔 채로 시작한다 (lib/draftStore.ts)
  const [draft, setDraft] = useState(() => loadDraft(id))
  const [mode, setMode] = useState<'idle' | 'typing' | 'voice'>(() => (loadDraft(id) ? 'typing' : 'idle'))
  useEffect(() => saveDraft(id, draft), [id, draft])
  const [cardOpen, setCardOpen] = useState(false)
  const [progressOpen, setProgressOpen] = useState(false)
  const [resumeOpen, setResumeOpen] = useState(true)
  // 단계를 넘긴 직후의 전환 화면 (넘기기 전 단계)
  const [transitionFrom, setTransitionFrom] = useState<number | null>(null)
  // 대답마다 방금 생긴 재료 (진행 신호 3층). 이 화면에 있는 동안만 보인다
  const [receipts, setReceipts] = useState<Record<string, Material[]>>({})
  const lastUserIdRef = useRef<string | null>(null)
  // 만들어지는 중인 질문 (question_delta를 이어 붙인 것). null이면 없음
  const [streaming, setStreaming] = useState<string | null>(null)
  const historyEnd = useRef<HTMLDivElement>(null)
  const [readAloud, setReadAloud] = useReadAloud()
  // onEvent 안에서 최신 값을 읽기 위한 ref
  const readAloudRef = useRef(readAloud)
  const lastInputRef = useRef<'voice' | 'text'>('text')
  useEffect(() => {
    readAloudRef.current = readAloud
  }, [readAloud])
  useStopSpeakingOnUnmount()
  // 말로 답하기: 서버 받아쓰기 > 브라우저 인식 > 없음
  const voiceMode = useVoiceInput()
  const voiceModeRef = useRef(voiceMode)
  useEffect(() => {
    voiceModeRef.current = voiceMode
  }, [voiceMode])

  useEffect(() => {
    Promise.all([api.getSession(id), api.turns(id)])
      .then(([s, t]) => {
        setSession(s)
        setTurns(t)
      })
      .catch((e) => setError(String(e.message ?? e)))
  }, [id])

  const isStreaming = streaming !== null
  useEffect(() => {
    // 최신 Chromium의 scrollIntoView는 Promise를 돌려준다. effect가 그걸 반환하면 안 된다
    void historyEnd.current?.scrollIntoView({ block: 'end' })
  }, [turns.length, isStreaming])

  const onEvent = useCallback((e: TurnEvent) => {
    switch (e.event) {
      case 'status':
        setStatus(STEP_TEXT[e.data.step])
        break
      case 'materials': {
        setSession(e.data.session)
        const userId = lastUserIdRef.current
        if (userId) setReceipts((r) => ({ ...r, [userId]: e.data.added }))
        break
      }
      case 'card':
        setCardOpen(true)
        break
      case 'question_delta':
        // 질문이 만들어지는 대로 보여 준다 (속도감)
        setStreaming((q) => (q ?? '') + e.data.text)
        setStatus(null)
        break
      case 'question_reset':
        // 빠른 규칙 검사에 걸려 다시 만드는 중
        setStreaming('')
        setStatus(STEP_TEXT.reviewing)
        break
      case 'question':
        setStreaming(null)
        setTurns((t) => [...t, e.data.turn])
        setStatus(null)
        if (readAloudRef.current) {
          // 말로 답하던 중이면, 다 읽은 뒤 바로 말하기 화면을 연다 (손 안 쓰는 대화)
          const handsFree = lastInputRef.current === 'voice' && voiceModeRef.current !== 'none'
          speak(e.data.turn.text, { sessionId: id, onEnd: handsFree ? () => setMode('voice') : undefined })
        }
        break
      case 'error':
        setError(e.data.message)
        setStreaming(null)
        setStatus(null)
        break
    }
  }, [id])

  const busy = status !== null

  const send = async (text: string, input_mode: 'voice' | 'text', skip = false, stuck = false) => {
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
    lastUserIdRef.current = optimistic.id
    setStatus(STEP_TEXT.asking)
    try {
      await api.sendTurn(id, { text, input_mode, skip, stuck }, onEvent)
    } catch (e) {
      // 서버에 닿기 전에 실패했으면(네트워크, 하루 상한, 로그인 만료) 답은 저장되지 않았다.
      // 서버 기록으로 확인해서, 저장되지 않았으면 쓴 답을 입력창에 되돌린다
      const message = String((e as Error).message)
      const saved = await api.turns(id).catch(() => null)
      const lastUser = saved ? [...saved].reverse().find((t) => t.role === 'user') : undefined
      if (saved && lastUser?.text === text) {
        setTurns(saved)
        setError(message)
      } else {
        setTurns((t) => t.filter((x) => x.id !== optimistic.id))
        if (!skip && !stuck) {
          setDraft(text)
          setMode('typing')
          setError(`${withPeriod(message)} 쓰신 답은 입력창에 그대로 있어요.`)
        } else {
          setError(message)
        }
      }
    } finally {
      setStatus(null)
    }
  }

  // 새 단계의 여는 질문 (단계를 넘기거나 되돌린 뒤)
  const openStage = async () => {
    setTransitionFrom(null)
    setStatus(STEP_TEXT.asking)
    try {
      await api.openStage(id, onEvent)
    } catch (e) {
      setError(String((e as Error).message))
    } finally {
      setStatus(null)
    }
  }

  const moveStage = async (direction: 'advance' | 'back') => {
    setCardOpen(false)
    setProgressOpen(false)
    setTransitionFrom(null)
    setError(null)
    try {
      const from = session?.stage ?? 1
      const s = direction === 'advance' ? await api.advance(id) : await api.back(id)
      setSession(s)
      // 넘긴 뒤에는 전환 화면에서 모은 것과 다음 할 일을 먼저 보여 주고, 사용자가 시작을 누르면 묻는다
      if (direction === 'advance') {
        setTransitionFrom(from)
        return
      }
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
        <Journey stage={session.stage} progress={session.progress} onClick={() => setProgressOpen(true)} />
        {session.stage <= 2 && (
          <ArcCurve
            arc={session.arc}
            next={session.progress.next_block}
            onClick={() => setProgressOpen(true)}
          />
        )}
        {session.repeated.length > 0 && (
          <p className="repeated">
            반복된 말 {session.repeated.map((r) => `${r.value} ${r.count}회`).join(' · ')}
          </p>
        )}
      </header>

      {resumeOpen && <Resume session={session} turns={turns} onClose={() => setResumeOpen(false)} />}

      <div className="history" aria-label="지난 대화">
        {past.map((t, i) =>
          t.role === 'user' ? (
            <Answer key={t.id} text={t.text} next={past[i + 1]?.text ?? lastCoach?.text} added={receipts[t.id]} />
          ) : (
            <p key={t.id} className="past coach">
              {t.text}
            </p>
          ),
        )}
      </div>

      {lastCoach && (
        <section className="now" aria-live="polite">
          <p className="eyebrow row between">
            지금 질문 <ListenButton key={lastCoach.id} text={lastCoach.text} sessionId={id} />
          </p>
          <p className="question">
            <Quoted text={lastCoach.text} />
          </p>
          {!turns.some((t) => t.role === 'user') && (
            <p className="hint first-hint">
              한두 문장이면 충분해요. 언제, 어디였는지부터 떠오르는 대로 말해 보세요.
            </p>
          )}
        </section>
      )}
      {after.map((t) => (
        <Answer key={t.id} text={t.text} added={receipts[t.id]} mine />
      ))}
      {streaming !== null && (
        <section className="now streaming" aria-live="polite">
          <p className="eyebrow">다음 질문</p>
          <p className="question">
            {streaming}
            <span className="caret" aria-hidden />
          </p>
        </section>
      )}
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
            {voiceMode !== 'none' && (
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
        <div className="row center">
          <button type="button" className="link skip" disabled={busy} onClick={() => send(STUCK_TEXT, 'text', false, true)}>
            막혔어요
          </button>
          <span className="sep" aria-hidden>·</span>
          <button type="button" className="link skip" disabled={busy} onClick={() => send(SKIP_TEXT, 'text', true)}>
            이 질문은 넘어가기
          </button>
        </div>
      </footer>

      {mode === 'voice' && lastCoach && voiceMode !== 'none' && (
        <VoiceSheet
          sessionId={id}
          mode={voiceMode}
          question={lastCoach.text}
          repeated={session.repeated.map((r) => r.value)}
          onClose={() => setMode('idle')}
          onSend={(text) => send(text, 'voice')}
        />
      )}
      {progressOpen && (
        <ProgressSheet
          session={session}
          onClose={() => setProgressOpen(false)}
          onAdvance={() => moveStage('advance')}
          onCard={() => {
            setProgressOpen(false)
            setCardOpen(true)
          }}
        />
      )}
      {transitionFrom !== null && (
        <StageTransition
          from={transitionFrom}
          session={session}
          onContinue={openStage}
          onBack={() => moveStage('back')}
        />
      )}
      {cardOpen && (
        <MaterialCard sessionId={id} onMore={() => setCardOpen(false)} onAdvance={() => moveStage('advance')} />
      )}
    </div>
  )
}
