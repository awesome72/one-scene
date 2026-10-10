import type { Outline } from '../api/client'
import { go } from '../lib/route'

// 지금 재료로 쓸 수 있는 분량 (계열 짜기). 초안은 재료를 글로 옮긴 것이라, 모은 말의 글자 수가
// 초안 분량의 가장 가까운 짐작이다. 여정 시뮬레이션: 가장 빠른 경로로 넘어가면 초안이 목표의 1/5~1/3.
const ENOUGH = 0.6 // 이만큼 모이면 빈칸이 드물다
const THIN = 0.3 // 이보다 적으면 대화로 돌아가기를 권한다
const THIN_ITEM = 0.3 // 단락별: 예상 분량 대비 이보다 적으면 '재료 적음'

export function Coverage({ outline, sessionId }: { outline: Outline; sessionId: string }) {
  const seen = new Set<string>()
  let said = 0
  for (const item of outline.items) {
    for (const m of item.materials) {
      if (seen.has(m.id)) continue
      seen.add(m.id)
      said += m.text.length
    }
  }
  const target = outline.total_chars
  const ratio = target ? said / target : 1
  const thinItems = outline.items.filter(
    (i) => i.target_chars > 0 && i.materials.reduce((n, m) => n + m.text.length, 0) < i.target_chars * THIN_ITEM,
  )
  const round = (n: number) => Math.round(n / 50) * 50
  return (
    <section className="panel coverage" aria-label="지금 재료로 쓸 수 있는 분량">
      <p className="row between">
        <b>지금 재료로 쓸 수 있는 분량 약 {round(said).toLocaleString('ko-KR')}자</b>
        <span className="hint">목표 약 {target.toLocaleString('ko-KR')}자</span>
      </p>
      <div className="coverage-bar" aria-hidden>
        <i style={{ width: `${Math.min(100, ratio * 100)}%` }} className={ratio < THIN ? 'thin' : ''} />
      </div>
      <p className="hint">
        {ratio >= ENOUGH
          ? '목표 분량을 채울 만큼 말이 모였어요.'
          : ratio >= THIN
            ? '초안에 빈칸과 AI 제안이 조금 생길 수 있어요.'
            : '모은 말이 목표보다 많이 적어요. 대화로 돌아가 더 이야기하면 글이 길어지고 빈칸이 줄어요.'}
        {thinItems.length > 0 && ` 재료가 적은 단락: ${thinItems.map((i) => i.label).join(', ')}.`}
      </p>
      {ratio < THIN && (
        <button type="button" className="secondary wide" onClick={() => go({ name: 'chat', id: sessionId })}>
          대화로 돌아가 더 이야기하기
        </button>
      )}
    </section>
  )
}
