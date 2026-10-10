import { useEffect, useState } from 'react'
import { api, ARC_BLOCKS, ARC_SHORT, STAGE_NAMES, type ArcBlock, type Material, type MaterialCardData } from '../api/client'
import { josa } from '../lib/josa'

// SKILL.md 6장 길이 기준
const LENGTHS = [
  { id: 'short', name: '짧은 글', desc: '한 순간 · 약 1천 자' },
  { id: 'medium', name: '보통 글', desc: '한 시기 · 2~3천 자' },
  { id: 'long', name: '긴 글', desc: '긴 시간 · 4~6천 자' },
] as const

// 재료 카드 (목업 ④). 모두 사용자가 한 말 원문. 해석·의미 부여 없음 (SKILL.md 3장)
export function MaterialCard({
  sessionId,
  onMore,
  onAdvance,
}: {
  sessionId: string
  onMore: () => void
  onAdvance: () => void
}) {
  const [card, setCard] = useState<MaterialCardData | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.materialCard(sessionId).then(setCard).catch((e) => setError(String(e.message ?? e)))
  }, [sessionId])

  const toggle = async (materialId: string, excluded: boolean) => {
    await api.setExcluded(sessionId, materialId, excluded)
    setCard(await api.materialCard(sessionId))
  }

  // 블록 옮기기: 자동 분류가 틀렸을 때 사용자가 고친다 (예: 첫 장면의 사물이 지금 다시 나온 말 → 여운)
  const [moving, setMoving] = useState<string | null>(null)
  const move = async (materialId: string, block: ArcBlock) => {
    await api.moveMaterial(sessionId, materialId, block)
    setMoving(null)
    setCard(await api.materialCard(sessionId))
  }
  const row = (m: Material) => (
    <div key={m.id} className="material-row">
      <div className="row between">
        <button
          type="button"
          className={`said ${m.excluded ? 'off' : ''}`}
          aria-pressed={!m.excluded}
          onClick={() => toggle(m.id, !m.excluded)}
        >
          “{m.text}”
        </button>
        <button
          type="button"
          className="link small"
          aria-expanded={moving === m.id}
          onClick={() => setMoving(moving === m.id ? null : m.id)}
        >
          옮기기
        </button>
      </div>
      {moving === m.id && (
        <div className="tag-list" aria-label="옮길 블록">
          {ARC_BLOCKS.filter((b) => b !== m.arc_block).map((b) => (
            <button type="button" key={b} className="tag" onClick={() => move(m.id, b)}>
              {josa(ARC_SHORT[b], '으로', '로')}
            </button>
          ))}
        </div>
      )}
    </div>
  )

  // 주제·길이는 사용자가 직접 정하거나 고칠 수 있다 (open-questions F2)
  const [editingTopic, setEditingTopic] = useState(false)
  const [topic, setTopic] = useState('')
  const saveTopic = async () => {
    await api.updateSession(sessionId, { topic_sentence: topic.trim() })
    setEditingTopic(false)
    setCard(await api.materialCard(sessionId))
  }
  const setLength = async (target_length: 'short' | 'medium' | 'long') => {
    await api.updateSession(sessionId, { target_length })
    setCard(await api.materialCard(sessionId))
  }

  // 주제 후보: 사용자가 한 해석의 말(의미 블록, interpretation) 원문 그대로. 주제는 늘 사용자의 문장이다
  const pickTopic = async (text: string) => {
    await api.updateSession(sessionId, { topic_sentence: text })
    setCard(await api.materialCard(sessionId))
  }
  const topicChoices = card
    ? [...new Set(
        card.blocks
          .flatMap((b) => b.materials)
          .filter((m) => !m.excluded && (m.type === 'interpretation' || m.arc_block === 'meaning') && m.text.length >= 8)
          .map((m) => m.text),
      )]
        .sort((x, y) => y.length - x.length)
        .slice(0, 3)
    : []

  const next = card && card.stage < 4 ? STAGE_NAMES[card.stage + 1] : null

  return (
    <div className="sheet-backdrop" role="dialog" aria-label="재료 카드">
      <div className="sheet card">
        <header className="sheet-head">
          <h2>재료 카드</h2>
          <button type="button" className="link" onClick={onMore}>
            닫기
          </button>
        </header>
        {error && <p className="error">{error}</p>}
        {!card ? (
          <p className="hint">불러오는 중…</p>
        ) : (
          <>
            <p className="lead">
              {card.ready
                ? `${card.stage}단계 ${josa(card.stage_name, '을', '를')} 마칠 수 있어요`
                : `아직 채워지지 않은 것: ${card.missing.join(', ')}`}
            </p>
            <p className="sub">모두 당신이 한 말입니다. 쓰지 않을 재료는 눌러서 빼 둘 수 있어요.</p>

            <section className="card-block">
              <h3>
                한 문장 주제
                {!editingTopic && (
                  <button
                    type="button"
                    className="link"
                    onClick={() => {
                      setTopic(card.topic_sentence ?? '')
                      setEditingTopic(true)
                    }}
                  >
                    {card.topic_sentence ? '고치기' : '정하기'}
                  </button>
                )}
              </h3>
              {editingTopic ? (
                <form
                  className="row"
                  onSubmit={(e) => {
                    e.preventDefault()
                    saveTopic()
                  }}
                >
                  <input
                    autoFocus
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder="이 글은 무엇에 관한 이야기예요?"
                    aria-label="한 문장 주제"
                  />
                  <button type="submit" className="secondary" disabled={!topic.trim()}>
                    저장
                  </button>
                </form>
              ) : card.topic_sentence ? (
                <p className="said">{card.topic_sentence}</p>
              ) : (
                <>
                  <p className="hint">
                    {topicChoices.length
                      ? '내가 한 말 중에서 하나를 고르거나, 직접 적어 주세요.'
                      : '아직 정하지 않았어요. 직접 적어 주세요.'}
                  </p>
                  {topicChoices.length > 0 && (
                    <div className="tag-list column" aria-label="주제로 쓸 내 말">
                      {topicChoices.map((t) => (
                        <button type="button" key={t} className="tag" onClick={() => pickTopic(t)}>
                          “{t}”
                        </button>
                      ))}
                    </div>
                  )}
                </>
              )}
            </section>

            <section className="card-block">
              <h3>목표 길이</h3>
              <div className="row" role="radiogroup" aria-label="목표 길이">
                {LENGTHS.map((l) => (
                  <button
                    type="button"
                    key={l.id}
                    role="radio"
                    aria-checked={card.target_length === l.id}
                    className={`pattern ${card.target_length === l.id ? 'on' : ''}`}
                    onClick={() => setLength(l.id)}
                  >
                    <strong>{l.name}</strong>
                    <span>{l.desc}</span>
                  </button>
                ))}
              </div>
            </section>

            {card.blocks.map((b) => {
              const active = b.materials.filter((m) => !m.excluded).length
              return (
                <section key={b.block} className="card-block">
                  <h3>
                    {b.label}
                    <span>{b.materials.length ? (active ? `재료 ${active}개` : '빼 둠') : '비어 있음'}</span>
                  </h3>
                  {b.materials.map(row)}
                </section>
              )
            })}
            {card.unplaced.length > 0 && (
              <section className="card-block">
                <h3>
                  아직 자리가 없는 재료<span>옮기기로 블록을 정할 수 있어요</span>
                </h3>
                {card.unplaced.map(row)}
              </section>
            )}

            {card.repeated.length > 0 && (
              <section className="card-block">
                <h3>반복된 말</h3>
                <p>{card.repeated.map((r) => `${r.value} ${r.count}회`).join(' · ')}</p>
              </section>
            )}
            {card.gaps.length > 0 && (
              <section className="card-block">
                <h3>열린 틈</h3>
                <ul>
                  {card.gaps.map((g) => (
                    <li key={g}>{g}</li>
                  ))}
                </ul>
              </section>
            )}

            <div className="row">
              <button type="button" className="secondary" onClick={onMore}>
                조금 더 이야기하기
              </button>
              {next && (
                <button type="button" className="primary" onClick={onAdvance}>
                  {josa(next, '으로', '로')} 넘어가기
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
