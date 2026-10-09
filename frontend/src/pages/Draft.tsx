import { useEffect, useState } from 'react'
import { ApiError, api, type Draft as DraftData, type LintHit, type SessionDetail } from '../api/client'
import { Quoted } from '../components/Quoted'
import { StageBar } from '../components/StageBar'
import { VoiceSheet } from '../components/VoiceSheet'
import { go } from '../lib/route'
import { voiceSupported } from '../lib/speech'

const STEP_TEXT = { assembling: '초안을 다시 짜고 있어요', checking: '문장마다 출처를 확인하고 있어요' } as const

// 문장 하나를 교정 표시와 함께 그린다. 표시는 번호가 붙은 붉은 밑줄
function Sentence({
  text,
  hits,
  numbers,
  selected,
  onPick,
}: {
  text: string
  hits: LintHit[]
  numbers: Map<string, number>
  selected: string | null
  onPick: (id: string) => void
}) {
  const open = hits.filter((h) => !h.dismissed).sort((a, b) => a.start - b.start)
  const parts: React.ReactNode[] = []
  let at = 0
  for (const h of open) {
    if (h.start < at) continue
    if (h.start > at) parts.push(text.slice(at, h.start))
    parts.push(
      <button
        type="button"
        key={h.id}
        className={`mark ${selected === h.id ? 'on' : ''}`}
        aria-pressed={selected === h.id}
        onClick={(e) => {
          e.stopPropagation()
          onPick(h.id)
        }}
      >
        {text.slice(h.start, h.end)}
        <sup>{numbers.get(h.id)}</sup>
      </button>,
    )
    at = h.end
  }
  if (at < text.length) parts.push(text.slice(at))
  return <>{parts}</>
}

// 초안과 교정 (목업 ⑥): 고쳐 주지 않고 다시 묻는다
export function Draft({ id }: { id: string }) {
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [draft, setDraft] = useState<DraftData | null>(null)
  const [missing, setMissing] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [source, setSource] = useState<number | null>(null)
  const [answering, setAnswering] = useState<'text' | 'voice' | null>(null)
  const [answer, setAnswer] = useState('')
  const [answered, setAnswered] = useState(0)
  const [status, setStatus] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getSession(id).then(setSession).catch((e) => setError(String(e.message ?? e)))
    api
      .latestDraft(id)
      .then(setDraft)
      .catch((e) => (e instanceof ApiError && e.status === 404 ? setMissing(true) : setError(String(e.message))))
  }, [id])

  const redraft = async () => {
    setError(null)
    setSelected(null)
    setStatus(STEP_TEXT.assembling)
    try {
      await api.makeDraft(id, (e) => {
        if (e.event === 'status') setStatus(STEP_TEXT[e.data.step])
        if (e.event === 'error') setError(e.data.message)
        if (e.event === 'draft') {
          setDraft(e.data.draft)
          setMissing(false)
          setAnswered(0)
        }
      })
    } catch (e) {
      setError(String((e as Error).message))
    } finally {
      setStatus(null)
    }
  }

  if (!session) return <div className="page">{error ? <p className="error">{error}</p> : <p className="hint">불러오는 중…</p>}</div>

  const open = draft ? draft.hits.filter((h) => !h.dismissed) : []
  const numbers = new Map(open.map((h, i) => [h.id, i + 1]))
  const hit = open.find((h) => h.id === selected) ?? null

  const dismiss = async () => {
    if (!draft || !hit) return
    setDraft(await api.dismissHit(id, draft.id, hit.id))
    setSelected(null)
  }

  const sendAnswer = async (text: string, mode: 'voice' | 'text') => {
    if (!draft || !hit || !text.trim()) return
    setAnswering(null)
    setStatus('답을 받아 적고 있어요')
    try {
      const res = await api.answerHit(id, draft.id, hit.id, text.trim(), mode)
      setDraft(res.draft)
      setAnswered((n) => n + 1)
      setSelected(null)
      setAnswer('')
    } catch (e) {
      setError(String((e as Error).message))
    } finally {
      setStatus(null)
    }
  }

  return (
    <div className="page draft">
      <header className="chat-head">
        <div className="row between">
          <button type="button" className="link" onClick={() => go({ name: 'chat', id })}>
            ← 대화
          </button>
          <button type="button" className="link" onClick={() => go({ name: 'outline', id })}>
            순서 바꾸기
          </button>
        </div>
        <h1 className="title">{session.title || session.topic_sentence || '새 글'}</h1>
        <StageBar stage={session.stage} />
      </header>

      {missing && !draft && (
        <section className="panel">
          <p>아직 초안이 없어요.</p>
          <button type="button" className="primary" onClick={() => go({ name: 'outline', id })}>
            단락 순서 정하기
          </button>
        </section>
      )}

      {draft && (
        <>
          <p className="row between hint">
            <span>{open.length ? '붉은 표시를 누르면 질문이 열려요' : '열린 표시가 없어요'}</span>
            <span>
              {open.length}곳 · {draft.char_count.toLocaleString('ko-KR')}자 · {draft.version}번째 초안
            </span>
          </p>
          <article className="draft-body">
            {draft.paragraphs.map((p) => (
              <p key={p.position}>
                {p.sentences.map((s) => {
                  const sh = draft.hits.filter((h) => h.sentence === s.index)
                  const blankHit = sh.find((h) => h.kind === 'blank')
                  return (
                    <span key={s.index}>
                      {s.is_blank ? (
                        blankHit && !blankHit.dismissed ? (
                          <button
                            type="button"
                            className={`mark blank ${selected === blankHit.id ? 'on' : ''}`}
                            onClick={() => setSelected(blankHit.id)}
                          >
                            ‸ 비워 둔 자리<sup>{numbers.get(blankHit.id)}</sup>
                          </button>
                        ) : (
                          <span className="blank-kept">‸ 비워 둔 자리</span>
                        )
                      ) : (
                        <span
                          className={`sentence ${source === s.index ? 'on' : ''}`}
                          onClick={() => setSource(source === s.index ? null : s.index)}
                        >
                          <Sentence
                            text={s.text}
                            hits={sh}
                            numbers={numbers}
                            selected={selected}
                            onPick={setSelected}
                          />
                        </span>
                      )}{' '}
                      {source === s.index && (
                        <span className="source">
                          출처: {s.materials.map((m) => `“${m.text}”`).join(' · ')}
                        </span>
                      )}
                    </span>
                  )
                })}
              </p>
            ))}
          </article>
          <p className="hint">모든 문장은 대화에서 나온 당신의 말에 연결되어 있어요. 문장을 누르면 출처가 보여요.</p>
          {answered > 0 && (
            <p className="note">답한 {answered}곳은 재료가 되었어요. 초안을 다시 만들면 반영돼요.</p>
          )}
        </>
      )}

      {status && (
        <p className="status" role="status">
          <span className="pulse" /> {status}
        </p>
      )}
      {error && <p className="error">{error}</p>}

      {draft && !hit && (
        <footer className="composer">
          <button type="button" className="secondary wide" disabled={status !== null} onClick={redraft}>
            초안 다시 만들기
          </button>
        </footer>
      )}

      {hit && (
        <div className="sheet-backdrop" onClick={() => setSelected(null)}>
          <div className="sheet" role="dialog" aria-label="교정 질문" onClick={(e) => e.stopPropagation()}>
            <header className="sheet-head">
              <h2>
                {numbers.get(hit.id)} / {open.length} · {hit.label}
              </h2>
              <button type="button" className="link" onClick={() => setSelected(null)}>
                닫기
              </button>
            </header>
            <p className="sub">{hit.why}</p>
            <p className="question">
              <Quoted text={hit.question} />
            </p>
            {answering === 'text' ? (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  sendAnswer(answer, 'text')
                }}
              >
                <textarea autoFocus rows={4} value={answer} onChange={(e) => setAnswer(e.target.value)} aria-label="답 쓰기" />
                <div className="row">
                  <button type="button" className="secondary" onClick={() => setAnswering(null)}>
                    취소
                  </button>
                  <button type="submit" className="primary" disabled={!answer.trim() || status !== null}>
                    보내기
                  </button>
                </div>
              </form>
            ) : (
              <>
                <div className="row">
                  {voiceSupported() && (
                    <button type="button" className="primary" onClick={() => setAnswering('voice')}>
                      말로 답하기
                    </button>
                  )}
                  <button type="button" className="secondary" onClick={() => setAnswering('text')}>
                    답 쓰기
                  </button>
                </div>
                <button type="button" className="link skip" onClick={dismiss}>
                  그대로 두기
                </button>
              </>
            )}
          </div>
        </div>
      )}
      {hit && answering === 'voice' && (
        <VoiceSheet
          question={hit.question}
          repeated={[]}
          onClose={() => setAnswering(null)}
          onSend={(text) => sendAnswer(text, 'voice')}
        />
      )}
    </div>
  )
}
