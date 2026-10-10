// 쓰는 중인 답을 이 브라우저에 잠시 보관한다: 새로고침하거나 보내기에 실패해도 기억을 꺼낸 글이 사라지지 않게.
// 보내기에 성공하면 지운다. 저장이 막힌 브라우저(사생활 보호 창 등)에서는 조용히 넘어간다
const key = (name: string) => `one-scene.draft.${name}`

export function loadDraft(name: string): string {
  try {
    return localStorage.getItem(key(name)) ?? ''
  } catch {
    return ''
  }
}

export function saveDraft(name: string, text: string): void {
  try {
    if (text.trim()) localStorage.setItem(key(name), text)
    else localStorage.removeItem(key(name))
  } catch {
    // 보관하지 못해도 입력은 그대로 된다
  }
}

/** 오류 문구 뒤에 안내를 이어 붙일 때 문장을 끊는다 */
export function withPeriod(message: string): string {
  const m = message.trim()
  return /[.!?。]$/.test(m) ? m : `${m}.`
}
