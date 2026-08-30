import { Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { ChatPage } from '@/components/ChatPage'
import LoginScreen from '@/components/LoginScreen'
import { useAuthStore } from '@/stores/auth'

// 账号页（个人中心 / 用量）为次级页面，路径级懒加载拆分（用量含 echarts，避免进首屏主包）
const AccountLayout = lazy(() =>
  import('@/components/AccountLayout').then((module) => ({ default: module.AccountLayout })),
)
const ProfilePage = lazy(() =>
  import('@/components/ProfilePage').then((module) => ({ default: module.ProfilePage })),
)
const UsagePage = lazy(() =>
  import('@/components/UsagePage').then((module) => ({ default: module.UsagePage })),
)

/** 次级页面 chunk 就绪前的占位（账号页 echarts 较重在后台加载） */
function PageLoading() {
  return (
    <div className="flex h-full min-w-0 flex-1 items-center justify-center gap-2 text-[13px] text-text-3">
      <Loader2 className="h-4 w-4 animate-spin text-brand-2" />
      加载中…
    </div>
  )
}

/** 登录页守卫：已登录访问 /login → 回退新对话页（未登录跳转 /login 由 AuthGate 在壳外把关） */
function RequireGuest({ children }: { children: ReactNode }) {
  const status = useAuthStore((s) => s.status)
  if (status === 'authenticated') return <Navigate to="/" replace />
  return <>{children}</>
}

/**
 * 应用路由表（纯客户端 SPA，BrowserRouter 由 main.tsx 包裹；CLAUDE.md 第 1 节）。
 * 五条页面路由：
 * - `/login` 登录页；`/` 新对话页；`/conversations/:conversationId` 会话页（URL 携带会话 ID）；
 * - `/profile` 个人中心、`/usage` 用量为独立页面（共享 AccountLayout 左导航，路径级懒加载）；
 * - 其余路径重定向 `/`。
 */
export default function App() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <RequireGuest>
            <LoginScreen />
          </RequireGuest>
        }
      />
      <Route path="/" element={<ChatPage />} />
      <Route path="/conversations/:conversationId" element={<ChatPage />} />
      <Route
        element={
          <Suspense fallback={<PageLoading />}>
            <AccountLayout />
          </Suspense>
        }
      >
        <Route
          path="/profile"
          element={
            <Suspense fallback={<PageLoading />}>
              <ProfilePage />
            </Suspense>
          }
        />
        <Route
          path="/usage"
          element={
            <Suspense fallback={<PageLoading />}>
              <UsagePage />
            </Suspense>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
