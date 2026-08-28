import { Lock, Moon, Phone, Sparkles, Sun } from 'lucide-react'
import type { FormEvent } from 'react'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTheme } from '@/hooks/useTheme'
import { useAuthStore } from '@/stores/auth'

/**
 * 登录页（ACCOUNT_API.md §1.1）：手机号 + 密码 → POST /auth/login 得 JWT。
 * 平台无注册接口（账号由管理侧预置）；页面不展示额外说明文案，仅品牌 + 表单。
 * 登录成功弹 toast 并让 auth store 进入 authenticated，由 AuthGate 切到主界面；
 * toast 由根层 Toaster 常驻（main.tsx Root），切屏后成功提示依然可见。
 * 明暗主题经 theme store 全局共享（登录页在 App 壳之外挂载，不持有独立主题态）。
 */
export default function LoginScreen() {
  const theme = useTheme()
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault()
      if (submitting) return
      const trimmed = phone.trim()
      if (trimmed === '' || password === '') {
        toast.warning('请输入手机号和密码')
        return
      }
      setSubmitting(true)
      const result = await useAuthStore.getState().login(trimmed, password)
      setSubmitting(false)
      if (!result.ok) {
        toast.error(result.message ?? '登录失败')
      } else {
        toast.success('登录成功')
      }
    },
    [phone, password, submitting],
  )

  return (
    <div className="relative flex h-full items-center justify-center px-4">
      <div className="chat-bg" aria-hidden="true" />
      <Button
        type="button"
        variant="ghost"
        size="icon"
        title={theme.isDark ? '切换浅色模式' : '切换深色模式'}
        onClick={theme.toggle}
        className="absolute right-4 top-4 text-text-2"
      >
        {theme.isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
      </Button>

      <div className="w-full max-w-sm rounded-2xl border border-border bg-surface-1 p-6 shadow-composer">
        <div className="mb-6 flex items-center justify-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-gradient text-white shadow-glow-brand ring-1 ring-brand-2/25">
            <Sparkles className="h-4 w-4" />
          </span>
          <span className="text-xl font-bold tracking-wide text-brand-gradient">Discover</span>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
          <label className="block" htmlFor="login-phone">
            <span className="mb-1.5 block text-[13px] font-medium text-text-2">手机号</span>
            <div className="relative">
              <Phone className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-3" />
              <Input
                id="login-phone"
                type="tel"
                value={phone}
                onChange={(event) => setPhone(event.target.value)}
                placeholder="请输入手机号"
                autoComplete="username"
                className="h-10 pl-9"
              />
            </div>
          </label>
          <label className="block" htmlFor="login-password">
            <span className="mb-1.5 block text-[13px] font-medium text-text-2">密码</span>
            <div className="relative">
              <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-3" />
              <Input
                id="login-password"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入密码"
                autoComplete="current-password"
                className="h-10 pl-9"
              />
            </div>
          </label>
          <Button type="submit" size="lg" disabled={submitting} className="mt-1 h-10">
            {submitting ? '登录中…' : '登录'}
          </Button>
        </form>
      </div>
    </div>
  )
}
