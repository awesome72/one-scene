import { useEffect, useRef, useState } from 'react'
import { josa } from '../lib/josa'
import { type Recognition, recognitionCtor } from '../lib/speech'
import { Quoted } from './Quoted'

// 말로 답하기 (목업 ③). 받아쓰기 → 확인·수정 → 보내기. 자동 전송하지 않는다.
// 지금은 브라우저 내장 음성 인식(Web Speech API)을 쓴다. Phase 5에서 서버 STT 어댑터로 바꾼다.



export function VoiceSheet({
  question,
  repeated,
  onSend,
  onClose,
}: {
  question: string
  repeated: string[]
  onSend: (text: string) => void
  onClose: () => void
}) {
  const [phase, setPhase] = useState<'listening' | 'confirm'>('listening')
  const [finalText, setFinalText] = useState('')
  const [interim, setInterim] = useState('')
  const [seconds, setSeconds] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const rec = useRef<Recognition | null>(null)

  const start = () => {
    const Ctor = recognitionCtor()
    if (!Ctor) return
    setFinalText('')
    setInterim('')
    setSeconds(0)
    setError(null)
    setPhase('listening')
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

  useEffect(() => {
    start()
    return () => rec.current?.stop()
  }, [])

  useEffect(() => {
    if (phase !== 'listening') return
    const t = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [phase])

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

        {phase === 'listening' ? (
          <>
            <p className="transcript live">{heard || '말씀하시면 여기에 적혀요.'}</p>
            <p className="listening">
              <span className="pulse" /> 듣고 있어요 {time}
            </p>
            {error && <p className="error">{error}</p>}
            <button type="button" className="primary wide" onClick={() => rec.current?.stop()}>
              다 말했어요
            </button>
          </>
        ) : (
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
