import { fileURLToPath, URL } from 'node:url'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

/**
 * Vite 配置：纯客户端 SPA（CLAUDE.md 第 1 节硬约束）。
 * - envDir ./env：VITE_* 自动流入 import.meta.env（Vite 原生支持，替代旧 Nuxt --dotenv 注入）。
 * - server.proxy：dev 环境 /api 反向代理到后端（读 VITE_PROXY_TARGET）。
 * - build.outDir dist：nginx 静态托管（Dockerfile / nginx.conf 对齐，见 CLAUDE.md 第 4 节）。
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, './env', '')
  // 优先级：进程内环境变量（docker compose 注入）> env/ 文件 > 默认。
  // loadEnv 只读 env/ 文件，故 compose 注入的 VITE_PROXY_TARGET 必须走 process.env 才生效。
  const apiProxyTarget =
    process.env.VITE_PROXY_TARGET || env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    envDir: './env',
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      // 端口被占时不自动递增（容器 / IDE 调试依赖固定端口）
      strictPort: true,
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
      // 单页应用单 chunk（react-dom + motion + radix 体积合理），提高阈值避免噪音
      chunkSizeWarningLimit: 800,
    },
  }
})
