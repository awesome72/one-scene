import { useState } from 'react'
import { ARC_BLOCKS, ARC_SHORT, type SessionDetail, type Turn } from '../api/client'

const DAY = 24 * 60 * 60 * 1000

// '지난번 여기까지': 사흘 이상 쉬었다 돌아오면 모은 재료와 마지막으로 한 말을 다시 보여 준다 (LLM 없이)
export function Resume({ session, turns, onClose }: { session: SessionDetail; turns: Turn[]; onClose: () => void }) {
  // 처음 그릴 때의 시각으로 고정 (렌더마다 바뀌지 않게)
  const [now] = useState(() => Date.now())
  const days = Math.floor((now - new Date(session.updated_at).getTime()) / DAY)
  if (days < 3) return null
  const lastUser = [...turns].reverse().find((t) => t.role === 'user')
  const filled = ARC_BLOCKS.filter((b) => session.arc[b] > 0).map((b) => `${ARC_SHORT[b]} ${session.arc[b]}`)
  return (
    <section className="panel resume" aria-label="지난번 여기까지">
      <p className="row between eyebrow">
        <span>지난번 여기까지 · {days}일 전</span>
        <button type="button" className="link" onClick={onClose}>
          닫기
        </button>
      </p>
      <p>
        재료 {session.material_count}개{filled.length > 0 && ` (${filled.join(', ')})`}
      </p>
      {lastUser && <p className="past user">{lastUser.text}</p>}
      {session.progress.next_need && (
        <p className="need">
          <b>다음 할 일</b> {session.progress.next_need}
        </p>
      )}
    </section>
  )
}
