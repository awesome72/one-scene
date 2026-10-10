import { useEffect, useRef, useState } from 'react'

const BARS = 14

// 말하는 동안 소리 크기 막대 (마이크가 실제로 듣고 있는지 보이기). level()은 0~1
export function LevelMeter({ level }: { level: () => number }) {
  const [bars, setBars] = useState<number[]>(() => Array(BARS).fill(0))
  const frame = useRef(0)
  useEffect(() => {
    let last = 0
    const tick = (t: number) => {
      if (t - last > 80) {
        last = t
        const v = level()
        setBars((b) => [...b.slice(1), v])
      }
      frame.current = requestAnimationFrame(tick)
    }
    frame.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame.current)
  }, [level])
  return (
    <span className="level-meter" aria-hidden>
      {bars.map((v, i) => (
        <i key={i} style={{ transform: `scaleY(${0.15 + v * 0.85})` }} />
      ))}
    </span>
  )
}
