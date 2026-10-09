import { useEffect, useState } from 'react'
import { api, type SessionDetail, type TagKind, type TagSet } from '../api/client'
import { StageBar } from '../components/StageBar'
import { go } from '../lib/route'

const KIND_LABEL: Record<TagKind, string> = {
  period: '시기',
  person: '인물',
  place: '장소',
  object: '핵심 사물',
  gap: '다음 글감',
}
const EMPTY: TagSet = { period: [], person: [], place: [], object: [], gap: [] }

// 마무리: 제목과 태그를 정하고 보관함에 넣는다 (SKILL.md 4-3). 태그는 제안일 뿐, 고르는 건 사용자
export function Finish({ id }: { id: string }) {
  const [session, setSession] = useState<SessionDetail | null>(null)
  const [title, setTitle] = useState('')
  const [tags, setTags] = useState<TagSet>(EMPTY)
  const [inputs, setInputs] = useState<Record<TagKind, string>>({ period: '', person: '', place: '', object: '', gap: '' })
  const [missing, setMissing] = useState<string[]>([])
  const [status, setStatus] = useState<string | null>('불러오는 중…')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    ;(async () => {
      try {
        const [s, saved, check] = await Promise.all([api.getSession(id), api.tags(id), api.finishCheck(id)])
        setSession(s)
        setTitle(s.title || s.topic_sentence || '')
        setMissing(check.filter((m) => m !== '태그'))
        const hasSaved = Object.values(saved).some((v) => v.length)
        if (hasSaved) setTags(saved)
        else {
          setStatus('태그를 제안하고 있어요')
          setTags(await api.suggestTags(id))
        }
      } catch (e) {
        setError(String((e as Error).message))
      } finally {
        setStatus(null)
      }
    })()
  }, [id])

  const remove = (kind: TagKind, value: string) => setTags((t) => ({ ...t, [kind]: t[kind].filter((v) => v !== value) }))
  const add = (kind: TagKind) => {
    const value = inputs[kind].trim()
    if (!value) return
    setTags((t) => ({ ...t, [kind]: t[kind].includes(value) ? t[kind] : [...t[kind], value] }))
    setInputs((i) => ({ ...i, [kind]: '' }))
  }

  const save = async () => {
    setError(null)
    setStatus('보관함에 넣고 있어요')
    try {
      await api.saveTags(id, tags)
      if (title.trim()) await api.updateSession(id, { title: title.trim() })
      await api.finish(id)
      go({ name: 'library' })
    } catch (e) {
      setError(String((e as Error).message))
      setStatus(null)
    }
  }

  return (
    <div className="page finish">
      <header className="chat-head">
        <button type="button" className="link" onClick={() => go({ name: 'draft', id })}>
          ← 초안
        </button>
        <h1 className="title">마무리하기</h1>
        {session && <StageBar stage={session.stage} />}
      </header>

      <label className="field">
        <span className="eyebrow">제목</span>
        <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="이 글의 이름" />
      </label>

      {(Object.keys(KIND_LABEL) as TagKind[]).map((kind) => (
        <section key={kind} className="card-block">
          <h3>
            {KIND_LABEL[kind]}
            {kind === 'gap' && <span>대화에서 나왔지만 아직 쓰지 않은 장면</span>}
          </h3>
          <div className={kind === 'gap' ? 'tag-list column' : 'tag-list'}>
            {tags[kind].map((v) => (
              <button type="button" key={v} className="tag" onClick={() => remove(kind, v)} aria-label={`${v} 빼기`}>
                {v} <span aria-hidden>×</span>
              </button>
            ))}
          </div>
          <form
            className="row"
            onSubmit={(e) => {
              e.preventDefault()
              add(kind)
            }}
          >
            <input
              value={inputs[kind]}
              onChange={(e) => setInputs((i) => ({ ...i, [kind]: e.target.value }))}
              placeholder={kind === 'gap' ? '다음에 쓰고 싶은 장면을 질문으로' : '더하기'}
              aria-label={`${KIND_LABEL[kind]} 더하기`}
            />
          </form>
        </section>
      ))}

      {missing.length > 0 && (
        <p className="note">아직 남은 것: {missing.join(', ')}. 이대로 보관해도 괜찮아요.</p>
      )}
      {status && (
        <p className="status" role="status">
          <span className="pulse" /> {status}
        </p>
      )}
      {error && <p className="error">{error}</p>}

      <footer className="composer">
        <button type="button" className="primary wide" disabled={status !== null} onClick={save}>
          보관함에 넣기
        </button>
      </footer>
    </div>
  )
}
