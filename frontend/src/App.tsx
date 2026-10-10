import './app.css'
import { useState } from 'react'
import { resetParams, useAuth } from './lib/auth'
import { useRoute } from './lib/route'
import { Chat } from './pages/Chat'
import { Draft } from './pages/Draft'
import { Finish } from './pages/Finish'
import { Home } from './pages/Home'
import { Library } from './pages/Library'
import { Login } from './pages/Login'
import { Outline } from './pages/Outline'
import { Privacy } from './pages/Privacy'
import { ResetPassword } from './pages/ResetPassword'

function App() {
  const route = useRoute()
  const [auth, refresh] = useAuth()
  // 비밀번호 재설정 메일의 링크로 돌아오면 주소에 ?token= (또는 ?error=)이 붙어 있다
  const [reset, setReset] = useState(() => {
    const p = resetParams()
    return p.token || p.error ? p : null
  })
  if (reset) return <ResetPassword token={reset.token} error={reset.error} onDone={() => setReset(null)} />
  // 개인정보 처리방침은 로그인 전에도 볼 수 있어야 한다
  if (route.name === 'privacy') return <Privacy />
  if (auth.status === 'loading') return <div className="page" />
  if (auth.status === 'signed-out') return <Login onDone={refresh} />
  switch (route.name) {
    case 'chat':
      return <Chat key={route.id} id={route.id} />
    case 'outline':
      return <Outline key={route.id} id={route.id} />
    case 'draft':
      return <Draft key={route.id} id={route.id} />
    case 'finish':
      return <Finish key={route.id} id={route.id} />
    case 'library':
      return <Library />
    default:
      return <Home user={auth.user} onSignOut={refresh} />
  }
}

export default App
