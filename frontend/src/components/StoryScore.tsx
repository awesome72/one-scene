import { useEffect, useState } from 'react'
import { api } from '../api/client'

// 완성 화면의 한 질문 (기획안 '내 이야기 같다' 만족도). 고르면 바로 저장, 다시 고르면 바뀐다
export function StoryScore({ sessionId }: { sessionId: string }) {
  const [score, setScore] = useState<number | null>(null)
  useEffect(() => {
    api.feedback(sessionId).then((f) => setScore(f.score)).catch(() => setScore(null))
  }, [sessionId])
  const pick = async (n: number) => {
    setScore(n)
    try {
      await api.saveFeedback(sessionId, n)
    } catch {
      // 저장에 실패해도 보관하기는 막지 않는다
    }
  }
  return (
    <section className="story-score" aria-label="이 글이 내 이야기 같나요?">
      <p className="label">이 글이 내 이야기 같나요?</p>
      <div className="score-row" role="radiogroup">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            type="button"
            key={n}
            role="radio"
            aria-checked={score === n}
            className={score === n ? 'on' : ''}
            onClick={() => pick(n)}
          >
            {n}
          </button>
        ))}
      </div>
      <p className="row between hint">
        <span>전혀 아니에요</span>
        <span>아주 그래요</span>
      </p>
    </section>
  )
}
