// 받침에 따라 조사를 고른다: josa('단락 구성', '으로', '로') → '단락 구성으로'
// 끝의 따옴표·괄호는 건너뛰고 마지막 한글 글자로 판단한다 (‘창밖’ → 창밖)
function batchim(word: string): number | null {
  const m = word.match(/([가-힣])[^가-힣]*$/)
  if (!m) return null
  return (m[1].charCodeAt(0) - 0xac00) % 28
}

export function josa(word: string, withBatchim: string, without: string): string {
  const b = batchim(word)
  // '으로/로'는 ㄹ 받침(8)일 때도 '로'
  const useWith = b !== null && b !== 0 && !(withBatchim === '으로' && b === 8)
  return word + (useWith ? withBatchim : without)
}
