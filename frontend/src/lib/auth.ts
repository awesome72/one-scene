// 로그인 (open-questions B2). Neon Auth(관리형 Better Auth).
// VITE_NEON_AUTH_URL이 있으면(운영) 로그인 필수, 없으면(로컬) 예전처럼 X-User-Id로 동작한다.
import { createAuthClient } from '@neondatabase/auth'
import { useEffect, useState } from 'react'

const url = import.meta.env.VITE_NEON_AUTH_URL as string | undefined

export const authEnabled = Boolean(url)
export const authClient = url ? createAuthClient(url) : null

export interface AuthUser {
  id: string
  email: string
  name: string | null
}

// API가 401을 받으면 이 이벤트로 로그인 화면을 다시 띄운다
export const AUTH_REQUIRED_EVENT = 'one-scene:auth-required'

async function session() {
  if (!authClient) return null
  const { data } = await authClient.getSession()
  return data ?? null
}

// 백엔드에 보낼 JWT. Neon Auth가 getSession 응답의 session.token에 JWT를 넣어 준다 (캐시됨)
export async function getToken(): Promise<string | null> {
  return (await session())?.session?.token ?? null
}

export async function getUser(): Promise<AuthUser | null> {
  const u = (await session())?.user
  return u ? { id: u.id, email: u.email, name: u.name ?? null } : null
}

function message(error: unknown, fallback: string): string {
  const e = error as { message?: string; code?: string; status?: number } | null
  if (!e) return fallback
  if (e.status === 401 || e.code === 'INVALID_EMAIL_OR_PASSWORD') return '이메일이나 비밀번호가 맞지 않아요.'
  if (e.code === 'USER_ALREADY_EXISTS' || e.code === 'USER_ALREADY_EXISTS_USE_ANOTHER_EMAIL')
    return '이미 가입한 이메일이에요. 로그인해 주세요.'
  if (e.code === 'PASSWORD_TOO_SHORT') return '비밀번호를 8자 이상으로 정해 주세요.'
  if (e.status === 403 || /origin/i.test(e.message ?? '')) return '지금은 로그인할 수 없어요. 잠시 뒤 다시 시도해 주세요.'
  return e.message || fallback
}

// Better Auth는 오류를 { error }로 돌려주기도 하고 예외로 던지기도 한다 (예: Invalid origin 403)
async function attempt(run: () => Promise<{ error: unknown }>, fallback: string): Promise<string | null> {
  try {
    const { error } = await run()
    return error ? message(error, fallback) : null
  } catch (e) {
    return message(e, fallback)
  }
}

export async function signIn(email: string, password: string): Promise<string | null> {
  if (!authClient) return null
  const client = authClient
  return attempt(() => client.signIn.email({ email, password }), '로그인하지 못했어요.')
}

export async function signUp(name: string, email: string, password: string): Promise<string | null> {
  if (!authClient) return null
  const client = authClient
  return attempt(() => client.signUp.email({ email, password, name }), '가입하지 못했어요.')
}

export async function signOut(): Promise<void> {
  await authClient?.signOut()
}

type AuthState = { status: 'loading' } | { status: 'signed-out' } | { status: 'signed-in'; user: AuthUser | null }

// 화면 전체의 로그인 상태
export function useAuth(): [AuthState, () => Promise<void>] {
  const [state, setState] = useState<AuthState>(
    authEnabled ? { status: 'loading' } : { status: 'signed-in', user: null },
  )
  const refresh = async () => {
    if (!authEnabled) return
    const user = await getUser().catch(() => null)
    setState(user ? { status: 'signed-in', user } : { status: 'signed-out' })
  }
  useEffect(() => {
    if (!authEnabled) return
    void refresh()
    const onRequired = () => setState({ status: 'signed-out' })
    window.addEventListener(AUTH_REQUIRED_EVENT, onRequired)
    return () => window.removeEventListener(AUTH_REQUIRED_EVENT, onRequired)
  }, [])
  return [state, refresh]
}
