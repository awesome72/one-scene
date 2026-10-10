import { useCallback, useEffect, useRef, useState } from 'react'
import { voiceApi } from '../api/client'
import { josa } from '../lib/josa'
import { type InputMode, Recorder } from '../lib/recorder'
import { type Recognition, recognitionCtor } from '../lib/speech'
import { stopSpeaking } from '../lib/tts'
import { LevelMeter } from './LevelMeter'
import { Quoted } from './Quoted'

// 말로 답하기 (목업 ③). 말하기 → 받아쓰기 → 확인·수정 → 보내기. 자동 전송하지 않는다.
// mode='server': 녹음해서 서버 받아쓰기(OpenAI, Phase 5). 모든 최신 브라우저에서 된다
// mode='browser': 브라우저 내장 인식(Chrome·Edge). 서버 음성을 못 쓸 때의 대비

const MAX_SECONDS = 180 // 서버 업로드 한도(4MB) 안쪽

export function VoiceSheet({
  sessionId,
  mode,
  question,
  repeated,
  onSend,
  onClose,
}: {
  sessionId: string
  mode: Exclude<InputMode, 'none'>
  question: string
  repeated: string[]
  onSend: (text: string) => void
  onClose: () => void
}) {
  const [phase, setPhase] = useState<'listening' | 'transcribing' | 'confirm'>('listening')
  const [finalText, setFinalText] = useState('')
  const [interim, setInterim] = useState('')
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const rec = useRef<Recognition | null>(null)
  const recorder = useRef<Recorder | null>(null)
  const recorderLevel = useCallback(() => recorder.current?.level() ?? 0, [])

  const reset = () => {
    stopSpeaking() // 읽어 주던 목소리가 녹음에 섞이지 않게
    setFinalText('')
    setInterim('')
    setSeconds(0)
    setError(null)
    setPhase('listening')
  }

  // ---------- 서버 받아쓰기 ----------
  const startServer = async () => {
    reset()
    const r = new Recorder()
    recorder.current = r
    try {
      await r.start()
    } catch {
      setError('마이크를 쓸 수 없어요. 브라우저 설정에서 마이크를 허용해 주세요.')
      setPhase('confirm')
    }
  }

  const finishServer = async () => {
    const r = recorder.current
    if (!r) return
    recorder.current = null
    setPhase('transcribing')
    try {
      const blob = await r.stop()
      setFinalText(await voiceApi.transcribe(sessionId, blob))
    } catch (e) {
      setError((e as Error).message || '잘 받아 적지 못했어요. 다시 말해 주세요.')
    } finally {
      setPhase('confirm')
    }
  }

  // ---------- 브라우저 내장 인식 ----------
  const startBrowser = () => {
    const Ctor = recognitionCtor()
    if (!Ctor) return
    reset()
    const r = new Ctor()
    r.lang = 'ko-KR'
    r.continuous = true
    r.interimResults = true
    r.onresult = (e) => {
      let fin = ''
      let mid = ''
      for (let i = 0; i < e.results.length; i++) {
        const res = e.results[i]
        if (res.isFinal) fin += res[0].transcript
        else mid += res[0].transcript
      }
      setFinalText(fin)
      setInterim(mid)
    }
    r.onerror = (e) => {
      if (e.error === 'not-allowed') setError('마이크 권한이 필요해요. 브라우저 설정에서 허용해 주세요.')
      else if (e.error !== 'no-speech' && e.error !== 'aborted') setError('잘 듣지 못했어요. 다시 말해 주세요.')
    }
    r.onend = () => {
      setInterim((mid) => {
        if (mid) setFinalText((f) => f + mid)
        return ''
      })
      setPhase('confirm')
    }
    rec.current = r
    r.start()
  }

  const start = () => (mode === 'server' ? void startServer() : startBrowser())
  const finish = () => (mode === 'server' ? void finishServer() : rec.current?.stop())

  // 효과 안에서는 최신 start/finish를 ref로 부른다
  const startRef = useRef(start)
  const finishRef = useRef(finish)
  useEffect(() => {
    startRef.current = start
    finishRef.current = finish
  })

  // 시트가 열릴 때 한 번만 듣기 시작한다 (다시 말하기는 버튼으로)
  useEffect(() => {
    startRef.current()
    return () => {
      rec.current?.stop()
      recorder.current?.cancel()
    }
  }, [])

  useEffect(() => {
    if (phase !== 'listening') return
    const t = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [phase])

  useEffect(() => {
    if (phase === 'listening' && seconds >= MAX_SECONDS) finishRef.current()
  }, [seconds, phase])

  const heard = (finalText + interim).trim()
  const hits = repeated.filter((w) => heard.includes(w))
  const time = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`

  return (
    <div className="sheet-backdrop" role="dialog" aria-label="말로 답하기">
      <div className="sheet voice">
        <header className="sheet-head">
          <h2>말로 답하기</h2>
          <button type="button" className="link" onClick={onClose}>
            닫기
          </button>
        </header>
        <p className="question small">
          <Quoted text={question} />
        </p>

        {phase === 'listening' && (
          <>
            <p className="transcript live">
              {mode === 'server' ? '편하게 말씀하세요. 다 말하면 받아 적어 드릴게요.' : heard || '말씀하시면 여기에 적혀요.'}
            </p>
            <p className="listening">
              {mode === 'server' ? (
                <LevelMeter level={recorderLevel} />
              ) : (
                <span className="pulse" />
              )}{' '}
              듣고 있어요 {time}
            </p>
            {error && <p className="error">{error}</p>}
            <button type="button" className="primary wide" onClick={finish}>
              다 말했어요
            </button>
          </>
        )}

        {phase === 'transcribing' && (
          <p className="status" role="status">
            <span className="pulse" /> 받아 적고 있어요
          </p>
        )}

        {phase === 'confirm' && (
          <>
            <h3 className="label">들은 내용을 확인해 주세요</h3>
            <textarea
              className="transcript"
              value={finalText}
              onChange={(e) => setFinalText(e.target.value)}
              rows={5}
              aria-label="받아쓴 내용"
            />
            <p className="hint">잘못 들은 곳은 눌러서 바로 고칠 수 있어요</p>
            {hits.length > 0 && (
              <p className="note">
                {josa(hits.map((w) => `‘${w}’`).join(', '), '이', '가')} 이 글에서 또 나왔어요. 반복된 말로
                기록해 둘게요.
              </p>
            )}
            {error && <p className="error">{error}</p>}
            <div className="row">
              <button type="button" className="secondary" onClick={start}>
                다시 말하기
              </button>
              <button
                type="button"
                className="primary"
                disabled={!finalText.trim()}
                onClick={() => onSend(finalText.trim())}
              >
                이대로 보내기
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
