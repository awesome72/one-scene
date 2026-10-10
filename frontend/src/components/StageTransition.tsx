import { ARC_BLOCKS, ARC_SHORT, STAGE_GOALS, STAGE_NAMES, type SessionDetail } from '../api/client'
import { josa } from '../lib/josa'
import { Journey } from './Journey'

// 단계 전환 (승인 직후 한 장): 평가 없이 모은 것, 다음에 할 일, 보통 분량만
export function StageTransition({
  from,
  session,
  onContinue,
  onBack,
}: {
  from: number
  session: SessionDetail
  onContinue: () => void
  onBack: () => void
}) {
  const p = session.progress
  return (
    <div className="sheet-backdrop" role="dialog" aria-label={`${from}단계를 마쳤어요`}>
      <div className="sheet transition">
        <Journey stage={session.stage} progress={p} />
        <p className="eyebrow">
          {from}단계 {josa(STAGE_NAMES[from], '을', '를')} 마쳤어요
        </p>
        <p className="lead">지금까지 모은 재료</p>
        <div className="collected">
          {ARC_BLOCKS.map((b) => (
            <div key={b}>
              <b>{session.arc[b]}</b>
              <small>{ARC_SHORT[b]}</small>
            </div>
          ))}
        </div>
        {(session.repeated.length > 0 || session.gaps.length > 0) && (
          <p className="hint">
            {session.repeated.length > 0 &&
              `반복된 말 ${session.repeated
                .slice(0, 2)
                .map((r) => `${r.value} ${r.count}회`)
                .join(', ')}`}
            {session.repeated.length > 0 && session.gaps.length > 0 && ' · '}
            {session.gaps.length > 0 && `열린 틈 ${session.gaps[0]}`}
          </p>
        )}
        <div className="nextstep">
          <span className="eyebrow">
            다음: {session.stage}단계 {STAGE_NAMES[session.stage]}
          </span>
          <b>{STAGE_GOALS[session.stage]}</b>
          <span>
            보통 {p.expected_turns[0]}~{p.expected_turns[1]}번 대답 · {p.expected_minutes[0]}~{p.expected_minutes[1]}분
          </span>
        </div>
        <button type="button" className="primary wide" onClick={onContinue}>
          {STAGE_NAMES[session.stage]} 시작하기
        </button>
        <button type="button" className="link" onClick={onBack}>
          {from}단계로 돌아가기
        </button>
      </div>
    </div>
  )
}
