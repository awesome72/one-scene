import { useEffect, useState } from 'react'

type ApiStatus = 'checking' | 'ok' | 'down'

function App() {
  const [api, setApi] = useState<ApiStatus>('checking')

  useEffect(() => {
    fetch('/api/health')
      .then((res) => setApi(res.ok ? 'ok' : 'down'))
      .catch(() => setApi('down'))
  }, [])

  return (
    <main>
      <h1 style={{ fontFamily: 'var(--serif)', fontSize: 22, margin: '0 0 8px' }}>한 장면</h1>
      <p style={{ color: 'var(--muted)', margin: 0 }}>
        한 장면은 글을 대신 쓰지 않습니다. 당신이 한 말만으로 글을 짓습니다.
      </p>
      <p style={{ color: 'var(--muted-2)', fontSize: 12, marginTop: 24 }}>
        서버 연결: {api === 'checking' ? '확인 중' : api === 'ok' ? '정상' : '연결 안 됨'}
      </p>
    </main>
  )
}

export default App
