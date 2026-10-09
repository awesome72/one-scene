import { useEffect, useState } from 'react'
import { api, STAGE_NAMES, type MaterialCardData } from '../api/client'
import { josa } from '../lib/josa'

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

            {card.topic_sentence && (
              <section className="card-block">
                <h3>한 문장 주제</h3>
                <p className="said">{card.topic_sentence}</p>
              </section>
            )}

            {card.blocks.map((b) => {
              const active = b.materials.filter((m) => !m.excluded).length
              return (
                <section key={b.block} className="card-block">
                  <h3>
                    {b.label}
                    <span>{b.materials.length ? (active ? `재료 ${active}개` : '빼 둠') : '비어 있음'}</span>
                  </h3>
                  {b.materials.map((m) => (
                    <button
                      type="button"
                      key={m.id}
                      className={`said ${m.excluded ? 'off' : ''}`}
                      aria-pressed={!m.excluded}
                      onClick={() => toggle(m.id, !m.excluded)}
                    >
                      “{m.text}”
                    </button>
                  ))}
                </section>
              )
            })}

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
