import { useEffect, useState } from 'react'

// 해시 라우팅: #/ (홈), #/s/{id} (대화). 화면이 몇 개 안 되어 라우터 라이브러리 없이 간다
export type Route = { name: 'home' } | { name: 'chat'; id: string }

function parse(hash: string): Route {
  const m = hash.match(/^#\/s\/([\w-]+)/)
  return m ? { name: 'chat', id: m[1] } : { name: 'home' }
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parse(location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}

export function go(route: Route): void {
  location.hash = route.name === 'home' ? '#/' : `#/s/${route.id}`
}
