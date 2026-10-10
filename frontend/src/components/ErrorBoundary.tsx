import { Component, type ReactNode } from 'react'

// 화면 그리기 중 오류가 나도 하얀 화면 대신 안내를 보여 준다 (쓴 글은 서버에 저장되어 있다)
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: unknown) {
    console.error('[one-scene] 화면 오류', error)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div className="page">
        <h1 className="logo">한 장면</h1>
        <p className="question small">화면을 그리다 문제가 생겼어요.</p>
        <p className="sub">지금까지 쓴 글과 대화는 저장되어 있어요.</p>
        <button
          type="button"
          className="primary wide"
          onClick={() => {
            location.hash = '#/'
            location.reload()
          }}
        >
          처음 화면으로
        </button>
      </div>
    )
  }
}
