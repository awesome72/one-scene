import { useEffect, useState } from 'react'

// 해시 라우팅: #/ 홈, #/library 보관함, #/s/{id} 대화,
// #/s/{id}/outline 계열 짜기, #/s/{id}/draft 초안과 교정, #/s/{id}/finish 마무리
export type Route =
  | { name: 'home' }
  | { name: 'library' }
  | { name: 'chat'; id: string }
  | { name: 'outline'; id: string }
  | { name: 'draft'; id: string }
  | { name: 'finish'; id: string }

type SubPage = 'outline' | 'draft' | 'finish'

function parse(hash: string): Route {
  if (hash.startsWith('#/library')) return { name: 'library' }
  const m = hash.match(/^#\/s\/([\w-]+)(?:\/(outline|draft|finish))?/)
  if (!m) return { name: 'home' }
  return { name: (m[2] as SubPage | undefined) ?? 'chat', id: m[1] }
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
  if (route.name === 'home') location.hash = '#/'
  else if (route.name === 'library') location.hash = '#/library'
  else if (route.name === 'chat') location.hash = `#/s/${route.id}`
  else location.hash = `#/s/${route.id}/${route.name}`
}
