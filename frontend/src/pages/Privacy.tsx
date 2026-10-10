import { go } from '../lib/route'

// 개인정보 처리방침 (로그인 없이 볼 수 있다). 실제 데이터 흐름(backend/app)과 맞춰 고친다
const UPDATED = '2026년 10월 10일'

const SECTIONS: { title: string; items: string[] }[] = [
  {
    title: '모으는 정보',
    items: [
      '계정: 이메일 주소와 비밀번호. 비밀번호는 로그인 서비스(Neon Auth)가 암호화해 보관하고, 한 장면은 볼 수 없습니다.',
      '글쓰기: 대화 원문(말로 답하면 받아 적은 글), 그 말에서 뽑은 재료, 개요, 초안, 태그, 제목, "내 이야기 같다" 점수.',
      '사용 기록: 하루 사용량 계산과 비용 확인을 위한 기록(언제 어떤 기능을 썼는지, AI 호출의 토큰 수와 비용), 단계 이동 기록. 이 기록에는 글 내용이 들어 있지 않습니다.',
    ],
  },
  {
    title: '녹음',
    items: [
      '말로 답하면 녹음 파일을 받아쓰기 서비스(OpenAI)로 보내 글로 바꿉니다. 녹음 파일은 한 장면 서버에 저장하지 않고, 받아 적은 뒤 버립니다.',
      '받아 적은 글은 보내기 전에 화면에서 확인하고 고칠 수 있으며, 보낸 글만 저장됩니다.',
    ],
  },
  {
    title: '다른 회사로 보내는 정보',
    items: [
      'Anthropic (미국): 질문 만들기, 재료 뽑기, 초안 조립과 검사, 태그 제안을 위해 대화 원문과 재료를 보냅니다.',
      'OpenAI (미국): 받아쓰기를 위해 녹음 파일을, 읽어 주기를 위해 코치의 질문 문장을 보냅니다.',
      'Neon (미국): 계정과 글을 저장하는 데이터베이스, 로그인.',
      'Vercel (미국): 웹사이트와 서버 운영.',
      'Anthropic과 OpenAI는 각 회사의 API 이용 정책에 따라, API로 보낸 데이터를 기본적으로 모델 학습에 쓰지 않습니다. 자세한 내용은 각 회사의 개인정보 처리방침을 확인해 주세요.',
    ],
  },
  {
    title: '브라우저에 남는 정보',
    items: [
      '로그인 상태, 쓰는 중인 답(보내기 전까지, 새로고침해도 남도록), 큰 글자 보기와 읽어 주기 같은 화면 설정. 이 기기의 브라우저에만 있고 서버로 보내지 않습니다.',
    ],
  },
  {
    title: '보관과 삭제',
    items: [
      '글은 직접 지울 때까지 보관합니다.',
      '글 하나는 홈의 "이 글 지우기"로, 모든 글은 보관함의 "내 글 모두 지우기"로 지울 수 있습니다. 대화, 재료, 초안, 태그, 점수, 단계 이동 기록이 함께 지워지고 되돌릴 수 없습니다.',
      '비용 기록은 서비스 운영 합계를 위해 남기되, 누구의 것인지 알 수 없게 바꿉니다.',
      '로그인 계정 자체의 삭제는 아직 화면에서 할 수 없습니다. 아래 문의처로 요청해 주세요.',
    ],
  },
]

export function Privacy() {
  return (
    <div className="page privacy">
      <header className="chat-head">
        <button type="button" className="link" onClick={() => (history.length > 1 ? history.back() : go({ name: 'home' }))}>
          ← 돌아가기
        </button>
        <h1 className="title">개인정보 처리방침</h1>
        <p className="hint">시행일 {UPDATED}</p>
      </header>
      <p>
        한 장면은 기억 속 이야기를 다룹니다. 무엇을 모으고, 어디로 보내고, 어떻게 지울 수 있는지 알려 드립니다.
      </p>
      {SECTIONS.map((s) => (
        <section key={s.title} className="privacy-section">
          <h2>{s.title}</h2>
          <ul>
            {s.items.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </section>
      ))}
      <section className="privacy-section">
        <h2>각 회사의 개인정보 처리방침</h2>
        <ul>
          <li>
            <a href="https://www.anthropic.com/legal/privacy" target="_blank" rel="noreferrer">
              Anthropic
            </a>
          </li>
          <li>
            <a href="https://openai.com/policies/privacy-policy/" target="_blank" rel="noreferrer">
              OpenAI
            </a>
          </li>
          <li>
            <a href="https://neon.com/privacy-policy" target="_blank" rel="noreferrer">
              Neon
            </a>
          </li>
          <li>
            <a href="https://vercel.com/legal/privacy-policy" target="_blank" rel="noreferrer">
              Vercel
            </a>
          </li>
        </ul>
      </section>
      <section className="privacy-section">
        <h2>문의</h2>
        <p>
          <a href="https://github.com/awesome72/one-scene/issues" target="_blank" rel="noreferrer">
            github.com/awesome72/one-scene/issues
          </a>
        </p>
      </section>
    </div>
  )
}
