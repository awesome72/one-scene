import { useEffect, useState } from 'react'
import { ApiError, api, type Draft as DraftData, type LintHit, type SessionDetail } from '../api/client'
import { ListenButton } from '../components/ListenButton'
import { Quoted } from '../components/Quoted'
import { StageBar } from '../components/StageBar'
import { VoiceSheet } from '../components/VoiceSheet'
import { copyText, download, markdown, plainText, safeFilename } from '../lib/exportText'
import { go } from '../lib/route'
import { useVoiceInput } from '../lib/recorder'
import { useStopSpeakingOnUnmount } from '../lib/tts'

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
  useStopSpeakingOnUnmount()
  const voiceMode = useVoiceInput()

  useEffect(() => {
    api.getSession(id).then(setSession).catch((e) => setError(String(e.message ?? e)))
    api
      .latestDraft(id)
      .then(setDraft)
      .catch((e) => (e instanceof ApiError && e.status === 404 ? setMissing(true) : setError(String(e.message))))
  }, [id])

  // 직접 고치기·꺼내기
  const [editing, setEditing] = useState(false)
  const [editText, setEditText] = useState<string[]>([])
  const [notice, setNotice] = useState<string | null>(null)
  const [editingSuggestion, setEditingSuggestion] = useState<string | null>(null)
  const [confirmRedraft, setConfirmRedraft] = useState(false)
  const hasEdited = draft?.paragraphs.some((p) => p.sentences.some((s) => s.edited)) ?? false
  const title = session?.title || session?.topic_sentence || '한 장면'

  const startEdit = () => {
    if (!draft) return
    setSelected(null)
    setEditText(draft.paragraphs.map((p) => p.sentences.map((s) => s.text).join(' ')))
    setEditing(true)
  }

  const saveEdit = async () => {
    if (!draft) return
    setError(null)
    setStatus('고친 글을 저장하고 있어요')
    try {
      setDraft(await api.editDraft(id, draft.id, editText.filter((t) => t.trim())))
      setEditing(false)
      setNotice('고친 글을 새 초안으로 저장했어요.')
    } catch (e) {
      setError(String((e as Error).message))
    } finally {
      setStatus(null)
    }
  }

  const blanksNote = () => (draft && draft.blank_count ? ` 비워 둔 자리 ${draft.blank_count}곳은 뺐어요.` : '')

  const copy = async () => {
    if (!draft) return
    const ok = await copyText(plainText(draft))
    setNotice(ok ? `글을 복사했어요.${blanksNote()}` : '복사하지 못했어요. 파일로 저장해 주세요.')
  }

  const save = (kind: 'txt' | 'md') => {
    if (!draft) return
    const name = `${safeFilename(title)}.${kind}`
    if (kind === 'md') download(name, markdown(draft, title), 'text/markdown')
    else download(name, `${title}\n\n${plainText(draft)}\n`)
    setNotice(`${name}로 저장했어요.${blanksNote()}`)
  }

  // AI 제안 받아들이기 (하나 / 모두)
  const acceptOne = async (index: number, text?: string) => {
    if (!draft) return
    setError(null)
    try {
      setDraft(await api.acceptSuggestion(id, draft.id, index, text))
      setSelected(null)
      setEditingSuggestion(null)
    } catch (e) {
      setError(String((e as Error).message))
    }
  }

  const acceptAll = async () => {
    if (!draft) return
    setError(null)
    try {
      const n = draft.suggestion_count
      setDraft(await api.acceptAll(id, draft.id))
      setNotice(`AI 제안 ${n}곳을 받아들였어요. 점선 문장은 언제든 직접 고칠 수 있어요.`)
    } catch (e) {
      setError(String((e as Error).message))
    }
  }

  const redraft = async () => {
    // 다시 만들면 재료로부터 새로 조립하므로, 고치거나 받아들인 문장은 빠진다 → 한 번 더 확인
    if (hasEdited && !confirmRedraft) {
      setConfirmRedraft(true)
      setNotice('다시 만들면 직접 고치거나 받아들인 문장은 새 초안에 들어가지 않아요. 한 번 더 누르면 다시 만들어요.')
      return
    }
    setConfirmRedraft(false)
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
  const hitSuggestion =
    hit && hit.kind === 'blank'
      ? draft?.paragraphs.flatMap((p) => p.sentences).find((x) => x.index === hit.sentence && x.suggestion) ?? null
      : null

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
          <div className="row toolbar">
            <button type="button" className="link" disabled={status !== null} onClick={startEdit}>
              {editing ? '고치는 중' : '직접 고치기'}
            </button>
            {draft.suggestion_count > 0 && (
              <button type="button" className="link" disabled={status !== null} onClick={acceptAll}>
                AI 제안 모두 받아들이기 ({draft.suggestion_count})
              </button>
            )}
            <button type="button" className="link" onClick={copy}>
              복사
            </button>
            <button type="button" className="link" onClick={() => save('txt')}>
              .txt 저장
            </button>
            <button type="button" className="link" onClick={() => save('md')}>
              .md 저장
            </button>
          </div>
          {notice && <p className="note">{notice}</p>}

          {editing ? (
            <form
              className="edit-draft"
              onSubmit={(e) => {
                e.preventDefault()
                void saveEdit()
              }}
            >
              <p className="hint">
                당신의 글이에요. 마음대로 고쳐도 돼요. 빈칸을 남기려면 [빈칸: …]을 그대로 두세요.
              </p>
              {editText.map((t, i) => (
                <textarea
                  key={i}
                  value={t}
                  rows={Math.max(3, Math.ceil(t.length / 22))}
                  onChange={(e) => setEditText((all) => all.map((x, j) => (j === i ? e.target.value : x)))}
                  aria-label={`${i + 1}번째 단락`}
                />
              ))}
              <div className="row">
                <button type="button" className="secondary" onClick={() => setEditing(false)}>
                  취소
                </button>
                <button type="submit" className="primary" disabled={status !== null}>
                  고친 글 저장
                </button>
              </div>
            </form>
          ) : (
          <article className="draft-body">
            {draft.paragraphs.map((p) => (
              <p key={p.position}>
                {p.sentences.map((s) => {
                  const sh = draft.hits.filter((h) => h.sentence === s.index)
                  const blankHit = sh.find((h) => h.kind === 'blank')
                  return (
                    <span key={s.index}>
                      {s.is_blank && s.suggestion && blankHit && !blankHit.dismissed ? (
                        <button
                          type="button"
                          className={`ai-suggestion ${selected === blankHit.id ? 'on' : ''}`}
                          onClick={() => setSelected(blankHit.id)}
                          aria-label="AI 제안 문장, 눌러서 받아들이거나 고치기"
                        >
                          <small>AI 제안</small>
                          {s.suggestion}
                          <sup>{numbers.get(blankHit.id)}</sup>
                        </button>
                      ) : s.is_blank ? (
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
                          className={`sentence ${source === s.index ? 'on' : ''} ${s.accepted ? 'accepted' : s.edited ? 'edited' : ''}`}
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
                          {s.accepted
                            ? '받아들인 AI 제안이에요.'
                            : s.edited
                            ? '직접 고친 문장이에요.'
                            : `출처: ${s.materials.map((m) => `“${m.text}”`).join(' · ')}`}
                        </span>
                      )}
                    </span>
                  )
                })}
              </p>
            ))}
          </article>
          )}
          <p className="hint">
            {hasEdited
              ? '점선 문장은 직접 고친 문장이에요. 나머지는 대화에서 나온 당신의 말에 연결되어 있어요.'
              : '모든 문장은 대화에서 나온 당신의 말에 연결되어 있어요. 문장을 누르면 출처가 보여요.'}
          </p>
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
          <div className="row">
            <button type="button" className="secondary" disabled={status !== null} onClick={redraft}>
              초안 다시 만들기
            </button>
            {session.stage === 4 && (
              <button
                type="button"
                className="primary"
                disabled={status !== null}
                onClick={() => go({ name: 'finish', id })}
              >
                {session.status === 'done' ? '태그 고치기' : '마무리하기'}
              </button>
            )}
          </div>
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
            {hitSuggestion ? (
              <>
                <p className="sub">재료가 비어 있던 자리에 AI가 쓴 문장이에요. 받아들여야 글이 돼요.</p>
                {editingSuggestion === null ? (
                  <p className="suggestion-box">{hitSuggestion.suggestion}</p>
                ) : (
                  <textarea
                    autoFocus
                    rows={3}
                    value={editingSuggestion}
                    onChange={(e) => setEditingSuggestion(e.target.value)}
                    aria-label="제안 고쳐 쓰기"
                  />
                )}
                <div className="row">
                  {editingSuggestion === null ? (
                    <>
                      <button
                        type="button"
                        className="primary"
                        disabled={status !== null}
                        onClick={() => acceptOne(hitSuggestion.index)}
                      >
                        이대로 받아들이기
                      </button>
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => setEditingSuggestion(hitSuggestion.suggestion ?? '')}
                      >
                        고쳐서 받아들이기
                      </button>
                    </>
                  ) : (
                    <>
                      <button type="button" className="secondary" onClick={() => setEditingSuggestion(null)}>
                        취소
                      </button>
                      <button
                        type="button"
                        className="primary"
                        disabled={!editingSuggestion.trim() || status !== null}
                        onClick={() => acceptOne(hitSuggestion.index, editingSuggestion)}
                      >
                        고친 문장 넣기
                      </button>
                    </>
                  )}
                </div>
                <p className="eyebrow">또는 내 기억으로 채우기</p>
              </>
            ) : (
              <p className="sub">{hit.why}</p>
            )}
            <p className="question">
              <Quoted text={hit.question} />
            </p>
            <ListenButton key={hit.id} text={hit.question} sessionId={id} />
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
                  {voiceMode !== 'none' && (
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
      {hit && answering === 'voice' && voiceMode !== 'none' && (
        <VoiceSheet
          sessionId={id}
          mode={voiceMode}
          question={hit.question}
          repeated={[]}
          onClose={() => setAnswering(null)}
          onSend={(text) => sendAnswer(text, 'voice')}
        />
      )}
    </div>
  )
}
