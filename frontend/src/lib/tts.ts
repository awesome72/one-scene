// 코치 질문 읽어 주기 (기획안 F9 음성 출력).
// 지금은 브라우저 내장 음성 합성(Web Speech API)을 쓴다. 서버 TTS로 바꿀 때는 이 파일만 고친다.
import { useEffect, useState } from 'react'

const PREF_KEY = 'one-scene.read-aloud'

export const ttsSupported = () => typeof window !== 'undefined' && 'speechSynthesis' in window

let koVoice: SpeechSynthesisVoice | null = null

function pickVoice(): SpeechSynthesisVoice | null {
  if (koVoice) return koVoice
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith('ko'))
  // 자연스러운 음성 우선: 온라인(Google/Microsoft Natural) → 로컬
  koVoice =
    voices.find((v) => /natural|online|google/i.test(v.name)) ?? voices.find((v) => v.localService) ?? voices[0] ?? null
  return koVoice
}

if (ttsSupported()) {
  // 음성 목록은 비동기로 채워진다
  window.speechSynthesis.addEventListener?.('voiceschanged', () => {
    koVoice = null
    pickVoice()
  })
}

export function speak(text: string, onEnd?: () => void): void {
  if (!ttsSupported() || !text.trim()) return
  const synth = window.speechSynthesis
  synth.cancel()
  // 따옴표 인용은 소리 내어 읽을 때 필요 없다
  const u = new SpeechSynthesisUtterance(text.replace(/[‘’“”"']/g, ''))
  u.lang = 'ko-KR'
  u.rate = 0.95
  const voice = pickVoice()
  if (voice) u.voice = voice
  if (onEnd) {
    u.onend = onEnd
    u.onerror = onEnd
  }
  synth.speak(u)
}

export function stopSpeaking(): void {
  if (ttsSupported()) window.speechSynthesis.cancel()
}

function readPref(): boolean {
  try {
    return localStorage.getItem(PREF_KEY) === 'on'
  } catch {
    return false
  }
}

// '질문 읽어 주기' 켜고 끄기. 브라우저마다 기억한다
export function useReadAloud(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(readPref)
  useEffect(() => {
    try {
      localStorage.setItem(PREF_KEY, on ? 'on' : 'off')
    } catch {
      /* 저장 못 해도 이번 화면에서는 동작 */
    }
    if (!on) stopSpeaking()
  }, [on])
  return [on, setOn]
}

// 화면을 떠나면 읽기를 멈춘다
export function useStopSpeakingOnUnmount(): void {
  useEffect(() => stopSpeaking, [])
}
