import './app.css'
import { useRoute } from './lib/route'
import { Chat } from './pages/Chat'
import { Home } from './pages/Home'

function App() {
  const route = useRoute()
  return route.name === 'chat' ? <Chat key={route.id} id={route.id} /> : <Home />
}

export default App
