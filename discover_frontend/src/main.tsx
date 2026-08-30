import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './App'
import AuthGate from './components/AuthGate'
import { Toaster } from './components/ui/sonner'
import { setUnauthorizedHandler } from './lib/api'
import { useAuthStore } from './stores/auth'
import { useThemeStore } from './stores/theme'
import './index.css'

// 全局 401 → 会话过期：api 层 axios 响应拦截器触发 auth store 的 expire
// （登录接口自身 401 已在拦截器内排除，不会误触）
setUnauthorizedHandler(() => {
  useAuthStore.getState().expire()
})

function setupGlobalErrorHandler(): void {
  window.addEventListener('error', (event) => {
    console.error('[discover][ERROR][global:error]', event.error ?? event.message)
  })
  window.addEventListener('unhandledrejection', (event) => {
    console.error('[discover][ERROR][global:unhandledrejection]', event.reason)
  })
}

setupGlobalErrorHandler()

/**
 * 应用根：Toaster 常驻根层（挂在 AuthGate 之上，不随登录态卸载）。
 * 登录页 / 主界面互斥挂载，toast 若挂在任一屏内，登录成功切屏即随卸载消失；
 * 根层保证登录页错误 / 成功提示在切到主界面后依然可见。主题经 theme store 全局共享。
 * BrowserRouter 包在 AuthGate 之外：登录页 / 主界面共享同一路由上下文，认证守卫统一跳转。
 */
function Root() {
  const isDark = useThemeStore((s) => s.isDark)
  return (
    <StrictMode>
      <BrowserRouter>
        <AuthGate>
          <App />
        </AuthGate>
        <Toaster theme={isDark ? 'dark' : 'light'} />
      </BrowserRouter>
    </StrictMode>
  )
}

// 运行时边界：index.html 中 id="root" 挂载点恒存在
const rootElement = document.getElementById('root')
if (rootElement !== null) {
  createRoot(rootElement).render(<Root />)
}
