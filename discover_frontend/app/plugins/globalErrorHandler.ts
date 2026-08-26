import { defineNuxtPlugin } from '#app'
import { setupGlobalErrorHandler } from '@/utils/logger'

/**
 * 客户端插件：全局错误边界（取代原 src/main.ts 的 setupGlobalErrorHandler 调用）。
 * ssr: false（SPA 模式）下始终在客户端执行；import.meta.client 守卫保留，兼容未来切换 SSR。
 */
export default defineNuxtPlugin(() => {
  if (import.meta.client) {
    setupGlobalErrorHandler()
  }
})
