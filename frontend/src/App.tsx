import './app.css'
import { useAuth } from './lib/auth'
import { useRoute } from './lib/route'
import { Chat } from './pages/Chat'
import { Draft } from './pages/Draft'
import { Finish } from './pages/Finish'
import { Home } from './pages/Home'
import { Library } from './pages/Library'
import { Login } from './pages/Login'
import { Outline } from './pages/Outline'

function App() {
  const route = useRoute()
  const [auth, refresh] = useAuth()
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
