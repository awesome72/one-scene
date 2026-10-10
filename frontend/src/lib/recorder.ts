// 녹음 (Phase 5). 모든 최신 브라우저(iOS Safari 포함)의 MediaRecorder로 녹음해 서버 받아쓰기로 보낸다
import { useEffect, useState } from 'react'
import { voiceApi } from '../api/client'
import { recognitionCtor } from './speech'

export const recorderSupported = () =>
  typeof window !== 'undefined' && Boolean(navigator.mediaDevices?.getUserMedia) && 'MediaRecorder' in window

// 브라우저마다 되는 형식이 다르다: Chrome·Firefox는 webm/ogg, Safari는 mp4
function pickMime(): string {
  for (const type of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']) {
    if (MediaRecorder.isTypeSupported(type)) return type
  }
  return ''
}

export class Recorder {
  private media: MediaRecorder | null = null
  private stream: MediaStream | null = null
  private chunks: Blob[] = []

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    })
    const mimeType = pickMime()
    this.media = new MediaRecorder(this.stream, mimeType ? { mimeType, audioBitsPerSecond: 32_000 } : undefined)
    this.chunks = []
    this.media.ondataavailable = (e) => {
      if (e.data.size) this.chunks.push(e.data)
    }
    this.media.start(1000)
  }

  stop(): Promise<Blob> {
    return new Promise((resolve) => {
      const media = this.media
      if (!media || media.state === 'inactive') {
        this.release()
        resolve(new Blob(this.chunks))
        return
      }
      media.onstop = () => {
        const blob = new Blob(this.chunks, { type: media.mimeType || 'audio/webm' })
        this.release()
        resolve(blob)
      }
      media.stop()
    })
  }

  cancel(): void {
    if (this.media && this.media.state !== 'inactive') this.media.stop()
    this.release()
  }

  private release(): void {
    this.stream?.getTracks().forEach((t) => t.stop()) // 마이크 표시등을 끈다
    this.stream = null
  }
}

// 서버 음성 설정은 한 번만 묻는다
let configPromise: Promise<{ stt: boolean; tts: boolean }> | null = null
export function serverVoice(): Promise<{ stt: boolean; tts: boolean }> {
  configPromise ??= voiceApi.config().catch(() => ({ stt: false, tts: false }))
  return configPromise
}

export type InputMode = 'server' | 'browser' | 'none'

// 말로 답하기를 어떻게 할지: 서버 받아쓰기 > 브라우저 내장 인식 > 없음
export function useVoiceInput(): InputMode {
  const browser: InputMode = recognitionCtor() ? 'browser' : 'none'
  const [mode, setMode] = useState<InputMode>(browser)
  useEffect(() => {
    if (!recorderSupported()) return
    void serverVoice().then((c) => {
      if (c.stt) setMode('server')
    })
  }, [])
  return mode
}
