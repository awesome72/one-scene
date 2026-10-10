import { useState } from 'react'
import { signIn, signUp } from '../lib/auth'

// 로그인·가입. 글은 내 기억이라, 나만 볼 수 있게 계정으로 지킨다
export function Login({ onDone }: { onDone: () => void }) {
  const [mode, setMode] = useState<'signin' | 'signup'>('signin')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    setBusy(true)
    setError(null)
    const err = mode === 'signin' ? await signIn(email.trim(), password) : await signUp(name.trim(), email.trim(), password)
    setBusy(false)
    if (err) setError(err)
    else onDone()
  }

  return (
    <div className="page login">
      <header className="top">
        <h1 className="logo">한 장면</h1>
      </header>
      <p className="question">
        묻는 AI, 쓰는 사람.
        <br />
        기억 속 한 장면에서 시작해요.
      </p>
      <form
        className="panel"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <p className="eyebrow">{mode === 'signin' ? '로그인' : '처음 오셨어요'}</p>
        {mode === 'signup' && (
          <label className="field">
            <span className="sub">부를 이름</span>
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
          </label>
        )}
        <label className="field">
          <span className="sub">이메일</span>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
        </label>
        <label className="field">
          <span className="sub">비밀번호{mode === 'signup' && ' (8자 이상)'}</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
            minLength={8}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" className="primary wide" disabled={busy}>
          {busy ? '잠시만요…' : mode === 'signin' ? '로그인' : '가입하고 시작하기'}
        </button>
        <button
          type="button"
          className="link"
          onClick={() => {
            setMode(mode === 'signin' ? 'signup' : 'signin')
            setError(null)
          }}
        >
          {mode === 'signin' ? '처음이에요, 가입할게요' : '이미 계정이 있어요'}
        </button>
      </form>
      <p className="footnote">한 장면은 당신의 말로 글을 짓고, AI는 빈 곳에 제안만 합니다. 쓴 글과 대화는 당신만 볼 수 있어요.</p>
      <p className="footnote">
        대화는 질문을 만들기 위해 AI 서비스로 보내집니다. 무엇을 어디로 보내는지는{' '}
        <a href="#/privacy">개인정보 처리방침</a>에 있어요.
      </p>
    </div>
  )
}
