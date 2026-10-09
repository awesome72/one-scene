import './app.css'
import { useRoute } from './lib/route'
import { Chat } from './pages/Chat'
import { Draft } from './pages/Draft'
import { Finish } from './pages/Finish'
import { Home } from './pages/Home'
import { Library } from './pages/Library'
import { Outline } from './pages/Outline'

function App() {
  const route = useRoute()
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
      return <Home />
  }
}

export default App
