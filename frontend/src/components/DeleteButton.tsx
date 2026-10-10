import { useState } from 'react'

// 되돌릴 수 없는 지우기: 한 번 더 확인한다 (브라우저 확인 창 대신 버튼 두 번)
export function DeleteButton({
  label,
  confirmLabel,
  onDelete,
}: {
  label: string
  confirmLabel: string
  onDelete: () => Promise<void>
}) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  if (!asking) {
    return (
      <button type="button" className="link danger" onClick={() => setAsking(true)}>
        {label}
      </button>
    )
  }
  return (
    <span className="confirm-delete" role="group" aria-label="지우기 확인">
      <span className="sub">{confirmLabel}</span>
      <button
        type="button"
        className="link danger"
        disabled={busy}
        onClick={async () => {
          setBusy(true)
          try {
            await onDelete()
          } finally {
            setBusy(false)
            setAsking(false)
          }
        }}
      >
        지우기
      </button>
      <button type="button" className="link" onClick={() => setAsking(false)}>
        취소
      </button>
    </span>
  )
}
