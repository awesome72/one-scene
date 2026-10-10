import { useState } from 'react'

// 첫 안내 세 장: 서비스의 세 가지 약속과 글 한 편의 분량. 한 번 보면 다시 뜨지 않는다
const CARDS = [
  {
    title: 'AI는 묻기만 합니다',
    body: '한 번에 질문 하나. 방금 하신 말의 한 구절을 이어받아, 기억 속 장면을 하나씩 묻습니다.',
  },
  {
    title: '말로 답해도 됩니다',
    body: '누르고 말하면 받아 적고, 보내기 전에 확인합니다. 녹음 원본은 받아 적은 뒤 지웁니다.',
  },
  {
    title: '당신이 한 말만 씁니다',
    body: '초안의 문장은 모두 대화 속 당신의 말에서 나옵니다. 글 한 편은 보통 40~70분, 며칠에 나눠 써도 됩니다.',
  },
]

export function Onboarding({ onDone }: { onDone: () => void }) {
  const [i, setI] = useState(0)
  const card = CARDS[i]
  const last = i === CARDS.length - 1
  return (
    <div className="sheet-backdrop" role="dialog" aria-label="한 장면 안내">
      <div className="sheet onboarding">
        <p className="eyebrow">
          {i + 1} / {CARDS.length}
        </p>
        <p className="lead">{card.title}</p>
        <p className="onboarding-body">{card.body}</p>
        <div className="dots" aria-hidden>
          {CARDS.map((_, j) => (
            <i key={j} className={j === i ? 'on' : ''} />
          ))}
        </div>
        <button type="button" className="primary wide" onClick={() => (last ? onDone() : setI(i + 1))}>
          {last ? '시작하기' : '다음'}
        </button>
        {!last && (
          <button type="button" className="link" onClick={onDone}>
            건너뛰기
          </button>
        )}
      </div>
    </div>
  )
}
