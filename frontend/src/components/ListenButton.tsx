import { useState } from 'react'
import { speak, stopSpeaking, ttsSupported } from '../lib/tts'

// 질문 다시 듣기 버튼
export function ListenButton({ text }: { text: string }) {
  const [playing, setPlaying] = useState(false)
  if (!ttsSupported()) return null
  return (
    <button
      type="button"
      className="listen"
      aria-label={playing ? '읽기 멈추기' : '질문 듣기'}
      onClick={() => {
        if (playing) {
          stopSpeaking()
          setPlaying(false)
        } else {
          setPlaying(true)
          speak(text, () => setPlaying(false))
        }
      }}
    >
      {playing ? '■ 멈추기' : '▶ 듣기'}
    </button>
  )
}
