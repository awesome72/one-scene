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
  // 말하는 동안 소리 크기 (마이크가 실제로 듣고 있는지 화면에 보이기 위해)
  private audio: AudioContext | null = null
  private analyser: AnalyserNode | null = null
  private samples: Uint8Array<ArrayBuffer> | null = null

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    })
    try {
      this.audio = new AudioContext()
      this.analyser = this.audio.createAnalyser()
      this.analyser.fftSize = 512
      this.audio.createMediaStreamSource(this.stream).connect(this.analyser)
      this.samples = new Uint8Array(this.analyser.fftSize)
    } catch {
      this.audio = null // 소리 크기 표시는 없어도 녹음은 된다
    }
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

  /** 지금 소리 크기 0~1 */
  level(): number {
    if (!this.analyser || !this.samples) return 0
    this.analyser.getByteTimeDomainData(this.samples)
    let sum = 0
    for (const v of this.samples) sum += ((v - 128) / 128) ** 2
    return Math.min(1, Math.sqrt(sum / this.samples.length) * 4)
  }

  private release(): void {
    this.stream?.getTracks().forEach((t) => t.stop()) // 마이크 표시등을 끈다
    this.stream = null
    void this.audio?.close().catch(() => {})
    this.audio = null
    this.analyser = null
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
