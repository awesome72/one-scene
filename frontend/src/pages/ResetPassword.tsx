import { useState } from 'react'
import { resetPassword } from '../lib/auth'

// 메일의 링크를 눌러 돌아온 화면: 새 비밀번호 정하기. 링크는 15분 동안 쓸 수 있다
export function ResetPassword({ token, error: linkError, onDone }: {
  token: string | null
  error: string | null
  onDone: () => void
}) {
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(
    linkError || !token ? '링크가 만료됐거나 올바르지 않아요. 로그인 화면에서 다시 요청해 주세요.' : null,
  )
  const [done, setDone] = useState(false)

  // 주소에서 토큰을 지우고 로그인 화면으로 (뒤로 가기로 토큰이 다시 쓰이지 않게)
  const leave = () => {
    history.replaceState(null, '', `${location.pathname}#/`)
    onDone()
  }

  const submit = async () => {
    if (!token) return
    setBusy(true)
    setError(null)
    const err = await resetPassword(token, password)
    setBusy(false)
    if (err) setError(err)
    else setDone(true)
  }

  return (
    <div className="page login">
      <header className="top">
        <h1 className="logo">한 장면</h1>
      </header>
      <form
        className="panel"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <p className="eyebrow">새 비밀번호 정하기</p>
        {done ? (
          <p className="hint">비밀번호를 바꿨어요. 새 비밀번호로 로그인해 주세요.</p>
        ) : (
          token && !linkError && (
            <label className="field">
              <span className="sub">새 비밀번호 (8자 이상)</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
            </label>
          )
        )}
        {error && <p className="error">{error}</p>}
        {!done && token && !linkError && (
          <button type="submit" className="primary wide" disabled={busy || password.length < 8}>
            {busy ? '잠시만요…' : '비밀번호 바꾸기'}
          </button>
        )}
        <button type="button" className="link" onClick={leave}>
          로그인 화면으로
        </button>
      </form>
    </div>
  )
}
