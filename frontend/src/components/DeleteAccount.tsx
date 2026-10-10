import { useState } from 'react'
import { api } from '../api/client'
import { authEnabled, deleteAccount, getUser, signIn, signOut } from '../lib/auth'

// 계정까지 지우기: 비밀번호 확인 → 내 글 모두 지우기 → 로그인 계정 지우기.
// 비밀번호를 먼저 확인해야, 틀린 비밀번호로 글만 지워지고 계정이 남는 일이 없다
export function DeleteAccount() {
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  if (!authEnabled) return null

  const run = async () => {
    setBusy(true)
    setMessage(null)
    const user = await getUser()
    if (!user) {
      setBusy(false)
      setMessage('로그인이 만료됐어요. 다시 로그인한 뒤 시도해 주세요.')
      return
    }
    const wrong = await signIn(user.email, password)
    if (wrong) {
      setBusy(false)
      setMessage('비밀번호가 맞지 않아요.')
      return
    }
    await api.deleteMyData()
    const err = await deleteAccount(password)
    setBusy(false)
    if (err) {
      setMessage(`쓴 글과 기록은 모두 지웠어요. ${err}`)
      return
    }
    await signOut()
    location.replace(`${location.pathname}#/`)
    location.reload()
  }

  if (!open) {
    return (
      <button type="button" className="link danger" onClick={() => setOpen(true)}>
        계정까지 지우기
      </button>
    )
  }
  return (
    <form
      className="confirm-delete column"
      onSubmit={(e) => {
        e.preventDefault()
        void run()
      }}
    >
      <span className="sub">
        쓴 글, 대화, 재료가 모두 지워지고 로그인 계정도 없어져요. 되돌릴 수 없어요. 비밀번호를 한 번 더 적어 주세요.
      </span>
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoComplete="current-password"
        aria-label="비밀번호 확인"
        required
      />
      {message && <p className="error">{message}</p>}
      <span className="row">
        <button type="submit" className="link danger" disabled={busy || !password}>
          {busy ? '지우는 중…' : '계정까지 지우기'}
        </button>
        <button type="button" className="link" onClick={() => setOpen(false)}>
          취소
        </button>
      </span>
    </form>
  )
}
