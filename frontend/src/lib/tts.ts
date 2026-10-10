// 코치 질문 읽어 주기 (기획안 F9 음성 출력).
// 서버 음성(OpenAI TTS, Phase 5)을 먼저 쓰고, 서버에 키가 없거나 실패하면 브라우저 내장 음성 합성으로 대비한다.
import { useEffect, useState } from 'react'
import { voiceApi } from '../api/client'
import { serverVoice } from './recorder'

const PREF_KEY = 'one-scene.read-aloud'
const CACHE_LIMIT = 30

const browserTts = () => typeof window !== 'undefined' && 'speechSynthesis' in window
export const ttsSupported = () => typeof window !== 'undefined' && ('Audio' in window || browserTts())

// ---------- 서버 음성 ----------

let audio: HTMLAudioElement | null = null
const cache = new Map<string, string>() // 글 → object URL (같은 질문을 다시 들을 때 재사용)
let generation = 0 // 멈추거나 새로 읽기 시작하면 늘어난다. 늦게 도착한 음성은 버린다

function player(): HTMLAudioElement {
  audio ??= new Audio()
  return audio
}

// iOS Safari는 사용자 터치 안에서 한 번 재생된 오디오 요소만 나중에 자동 재생할 수 있다
const SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA='
if (typeof window !== 'undefined') {
  const unlock = () => {
    const a = player()
    if (!a.src) {
      a.src = SILENT_WAV
      void a.play().catch(() => {})
    }
    window.removeEventListener('pointerdown', unlock)
  }
  window.addEventListener('pointerdown', unlock)
}

async function serverAudioUrl(sessionId: string, text: string): Promise<string> {
  const hit = cache.get(text)
  if (hit) return hit
  const url = URL.createObjectURL(await voiceApi.speech(sessionId, text))
  cache.set(text, url)
  if (cache.size > CACHE_LIMIT) {
    const [oldText, oldUrl] = cache.entries().next().value as [string, string]
    URL.revokeObjectURL(oldUrl)
    cache.delete(oldText)
  }
  return url
}

// ---------- 브라우저 음성 (대비) ----------

let koVoice: SpeechSynthesisVoice | null = null

function pickVoice(): SpeechSynthesisVoice | null {
  if (koVoice) return koVoice
  const voices = window.speechSynthesis.getVoices().filter((v) => v.lang.toLowerCase().startsWith('ko'))
  // 자연스러운 음성 우선: 온라인(Google/Microsoft Natural) → 로컬
  koVoice =
    voices.find((v) => /natural|online|google/i.test(v.name)) ?? voices.find((v) => v.localService) ?? voices[0] ?? null
  return koVoice
}

if (browserTts()) {
  // 음성 목록은 비동기로 채워진다
  window.speechSynthesis.addEventListener?.('voiceschanged', () => {
    koVoice = null
    pickVoice()
  })
}

function speakInBrowser(text: string, onEnd?: () => void): void {
  if (!browserTts()) {
    onEnd?.()
    return
  }
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

// ---------- 공개 함수 ----------

export interface SpeakOptions {
  // 서버 음성은 그 글의 질문만 읽어 준다 (남용 방지). 없으면 브라우저 음성
  sessionId?: string
  onEnd?: () => void
}

export function speak(text: string, { sessionId, onEnd }: SpeakOptions = {}): void {
  if (!text.trim()) return
  stopSpeaking()
  const mine = ++generation
  if (!sessionId) {
    speakInBrowser(text, onEnd)
    return
  }
  void (async () => {
    try {
      const { tts } = await serverVoice()
      if (!tts) throw new Error('서버 음성 없음')
      const url = await serverAudioUrl(sessionId, text)
      if (mine !== generation) return // 그사이 멈췄거나 다른 질문을 읽기 시작했다
      const a = player()
      a.onended = () => onEnd?.()
      a.onerror = () => onEnd?.()
      a.src = url
      await a.play()
    } catch {
      if (mine === generation) speakInBrowser(text, onEnd)
    }
  })()
}

export function stopSpeaking(): void {
  generation++
  if (audio) {
    audio.onended = null
    audio.onerror = null
    audio.pause()
  }
  if (browserTts()) window.speechSynthesis.cancel()
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
