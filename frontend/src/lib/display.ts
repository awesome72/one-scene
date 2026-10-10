// 화면 설정 (이 브라우저에만 저장): 큰 글자 보기, 첫 안내를 봤는지
const LARGE = 'one-scene.large-text'
const ONBOARDED = 'one-scene.onboarded'

function read(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1'
  } catch {
    return false
  }
}

function write(key: string, on: boolean): void {
  try {
    if (on) localStorage.setItem(key, '1')
    else localStorage.removeItem(key)
  } catch {
    // 저장이 막힌 브라우저에서도 이번 화면에서는 적용된다
  }
}

export function largeText(): boolean {
  return read(LARGE)
}

/** 큰 글자 보기 (63세 영수 님 페르소나): 문서 전체를 키운다 */
export function applyLargeText(on: boolean): void {
  write(LARGE, on)
  document.documentElement.classList.toggle('large-text', on)
}

export function onboarded(): boolean {
  return read(ONBOARDED)
}

export function markOnboarded(): void {
  write(ONBOARDED, true)
}
