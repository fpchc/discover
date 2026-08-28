import { Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect, useRef } from 'react'
import LoginScreen from '@/components/LoginScreen'
import { useAuthStore } from '@/stores/auth'

/**
 * 认证闸门（ACCOUNT_API.md §0）：应用唯一入口，按登录态分派——
 * loading → 启动恢复中（本地令牌校验 GET /users/me）；
 * unauthenticated → 登录页；authenticated → 挂载主界面（App 壳）。
 * 挂在 main.tsx 的 AuthGate 包裹层，保证主界面只在认证通过后渲染；
 * App 壳自身不判断登录态（App.test 直接渲染壳，绕过本闸门）。
 */
export default function AuthGate({ children }: { children: ReactNode }) {
  const status = useAuthStore((s) => s.status)
  // StrictMode 开发期 effect 双调用：只触发一次会话恢复
  const resolvedRef = useRef(false)

  useEffect(() => {
    if (resolvedRef.current) return
    resolvedRef.current = true
    void useAuthStore.getState().resolveSession()
  }, [])

  if (status === 'loading') {
    return (
      <div className="relative flex h-full items-center justify-center">
        <div className="chat-bg" aria-hidden="true" />
        <div className="flex flex-col items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-gradient text-white shadow-glow-brand ring-1 ring-brand-2/25">
            <Sparkles className="h-5 w-5" />
          </span>
          <span className="text-sm text-text-2">正在进入 Discover…</span>
        </div>
      </div>
    )
  }

  if (status === 'unauthenticated') {
    return <LoginScreen />
  }

  return <>{children}</>
}
