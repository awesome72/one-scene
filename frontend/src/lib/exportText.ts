// 완성 글 꺼내기: 복사·파일 저장. 빈칸("[빈칸: …]")은 글이 아니므로 뺀다
import type { Draft } from '../api/client'

export function plainText(draft: Draft): string {
  return draft.paragraphs
    .map((p) =>
      p.sentences
        .filter((s) => !s.is_blank)
        .map((s) => s.text)
        .join(' '),
    )
    .filter((p) => p.trim())
    .join('\n\n')
}

export function markdown(draft: Draft, title: string): string {
  return `# ${title}\n\n${plainText(draft)}\n`
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text)
    return true
  } catch {
    return false
  }
}

export function download(filename: string, text: string, type = 'text/plain'): void {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// 파일 이름에 쓸 수 없는 글자만 바꾼다
export function safeFilename(title: string): string {
  return title.replace(/[\\/:*?"<>|]/g, ' ').trim().slice(0, 60) || '한 장면'
}
