import { useEffect, useState } from 'react'

// 초안을 만드는 동안 (실측 약 30~40초): 지금 하는 일과 보통 걸리는 시간, 지난 시간을 보여 준다.
// 오래 걸리는 일 앞에서 멈춘 것처럼 보이지 않게 (여정 시뮬레이션 측정).
// 초안을 만드는 동안에만 그려지므로 처음 그려진 때가 시작 시각이다 (짜기 → 출처 확인으로 바뀌어도 이어서 센다)
const USUAL = '보통 30~40초'

export function DraftWait({ status }: { status: string }) {
  const [started] = useState(() => Date.now())
  const [now, setNow] = useState(started)
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  return (
    <p className="status" role="status">
      <span className="pulse" /> {status}
      <span className="sub"> · {USUAL} · {Math.floor((now - started) / 1000)}초 지남</span>
    </p>
  )
}
