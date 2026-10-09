// 백엔드 API 클라이언트. 서버가 상태의 원천이다 (CLAUDE.md)

export type ArcBlock = 'scene' | 'event' | 'meaning' | 'present' | 'resonance'

export const ARC_BLOCKS: ArcBlock[] = ['scene', 'event', 'meaning', 'present', 'resonance']
export const ARC_SHORT: Record<ArcBlock, string> = {
  scene: '장면',
  event: '사건',
  meaning: '의미',
  present: '현재',
  resonance: '여운',
}
export const STAGE_NAMES: Record<number, string> = {
  1: '주제 설정',
  2: '단락 구성',
  3: '계열 짜기',
  4: '태그와 교정',
}

export interface RepeatedWord {
  value: string
  count: number
}

export interface SessionSummary {
  id: string
  title: string | null
  stage: number
  stage_name: string
  status: string
  last_question: string | null
  updated_at: string
}

export interface SessionDetail extends SessionSummary {
  topic_sentence: string | null
  target_length: 'short' | 'medium' | 'long' | null
  sequence_pattern: string | null
  material_count: number
  arc: Record<ArcBlock, number>
  repeated: RepeatedWord[]
  gaps: string[]
}

export interface Turn {
  id: string
  idx: number
  role: 'user' | 'coach'
  text: string
  input_mode: 'voice' | 'text' | null
  stage: number
  created_at: string
}

export interface Material {
  id: string
  label: string
  text: string
  type: string
  arc_block: ArcBlock | null
  emotion_word: boolean
  excluded: boolean
}

export interface MaterialCardData {
  stage: number
  stage_name: string
  ready: boolean
  missing: string[]
  topic_sentence: string | null
  target_length: string | null
  blocks: { block: ArcBlock; label: string; materials: Material[] }[]
  unplaced: Material[]
  repeated: RepeatedWord[]
  gaps: string[]
}

export type PatternId = 'linear' | 'return' | 'frame' | 'cross'

export interface Outline {
  pattern: PatternId | null
  patterns: { id: PatternId; name: string; desc: string }[]
  items: { position: number; arc_block: ArcBlock; label: string; materials: Material[]; target_chars: number }[]
  total_chars: number
  saved: boolean
  bookends: string[]
}

export interface LintHit {
  id: string
  kind: string
  label: string
  sentence: number
  start: number
  end: number
  text: string
  why: string
  question: string
  dismissed: boolean
}

export interface Draft {
  id: string
  version: number
  created_at: string
  paragraphs: {
    position: number
    label: string | null
    sentences: { index: number; text: string; is_blank: boolean; materials: Material[] }[]
  }[]
  hits: LintHit[]
  open_hits: number
  char_count: number
  blank_count: number
}

export type DraftEvent =
  | { event: 'status'; data: { step: 'assembling' | 'checking' } }
  | { event: 'draft'; data: { draft: Draft } }
  | { event: 'error'; data: { message: string; detail?: string } }

export type TurnEvent =
  | { event: 'status'; data: { step: 'extracting' | 'asking' | 'reviewing'; attempt?: number } }
  | { event: 'materials'; data: { added: Material[]; session: SessionDetail } }
  | { event: 'card'; data: { stage: number } }
  | { event: 'question'; data: { turn: Turn } }
  | { event: 'error'; data: { message: string; detail?: string } }

// 개발 중 임시 인증: 브라우저마다 사용자 ID 하나 (open-questions B2)
function userId(): string {
  const key = 'one-scene.user-id'
  try {
    let id = localStorage.getItem(key)
    if (!id) {
      id = `u-${crypto.randomUUID().slice(0, 12)}`
      localStorage.setItem(key, id)
    }
    return id
  } catch {
    return 'dev-user'
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-User-Id': userId() },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let message = `요청이 실패했어요 (${res.status})`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') message = data.detail
    } catch {
      /* 본문 없음 */
    }
    throw new ApiError(res.status, message)
  }
  return res.json() as Promise<T>
}

// POST + SSE: EventSource는 GET만 되므로 fetch 스트림을 직접 읽는다
async function stream<E extends { event: string }>(
  path: string,
  body: unknown,
  onEvent: (e: E) => void,
): Promise<void> {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-User-Id': userId() },
    body: JSON.stringify(body ?? {}),
  })
  if (!res.ok || !res.body) throw new ApiError(res.status, `요청이 실패했어요 (${res.status})`)
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value.replace(/\r\n/g, '\n')
    let cut: number
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      let event = ''
      const data: string[] = []
      for (const line of block.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
      }
      if (event && data.length) onEvent({ event, data: JSON.parse(data.join('\n')) } as unknown as E)
    }
  }
}

export const api = {
  openingQuestions: () => request<string[]>('GET', '/opening-questions'),
  listSessions: () => request<SessionSummary[]>('GET', '/sessions'),
  createSession: (opening_question?: string) =>
    request<SessionDetail>('POST', '/sessions', { opening_question }),
  getSession: (id: string) => request<SessionDetail>('GET', `/sessions/${id}`),
  updateSession: (id: string, body: Partial<Pick<SessionDetail, 'title' | 'topic_sentence' | 'target_length'>>) =>
    request<SessionDetail>('PATCH', `/sessions/${id}`, body),
  turns: (id: string) => request<Turn[]>('GET', `/sessions/${id}/turns`),
  materialCard: (id: string) => request<MaterialCardData>('GET', `/sessions/${id}/material-card`),
  setExcluded: (id: string, materialId: string, excluded: boolean) =>
    request<Material>('PATCH', `/sessions/${id}/materials/${materialId}`, { excluded }),
  advance: (id: string) => request<SessionDetail>('POST', `/sessions/${id}/advance`, { approved: true }),
  back: (id: string) => request<SessionDetail>('POST', `/sessions/${id}/back`, { approved: true }),
  sendTurn: (
    id: string,
    body: { text: string; input_mode: 'voice' | 'text'; skip?: boolean },
    onEvent: (e: TurnEvent) => void,
  ) => stream(`/sessions/${id}/turns`, body, onEvent),
  openStage: (id: string, onEvent: (e: TurnEvent) => void) => stream(`/sessions/${id}/coach`, {}, onEvent),
  outline: (id: string, pattern?: PatternId) =>
    request<Outline>('GET', `/sessions/${id}/outline${pattern ? `?pattern=${pattern}` : ''}`),
  saveOutline: (id: string, pattern: PatternId) => request<Outline>('POST', `/sessions/${id}/outline`, { pattern }),
  makeDraft: (id: string, onEvent: (e: DraftEvent) => void) => stream(`/sessions/${id}/drafts`, {}, onEvent),
  latestDraft: (id: string) => request<Draft>('GET', `/sessions/${id}/drafts/latest`),
  dismissHit: (id: string, draftId: string, hitId: string) =>
    request<Draft>('POST', `/sessions/${id}/drafts/${draftId}/hits/${encodeURIComponent(hitId)}/dismiss`),
  answerHit: (id: string, draftId: string, hitId: string, text: string, input_mode: 'voice' | 'text') =>
    request<{ added: Material[]; draft: Draft }>(
      'POST',
      `/sessions/${id}/drafts/${draftId}/hits/${encodeURIComponent(hitId)}/answer`,
      { text, input_mode },
    ),
}
