import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

// 配置驱动：所有 URL / 阈值来自 VITE_*（见 src/config/env.ts 与 env/.env.*）
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, './env', '')
  const apiProxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'

  return {
    // 环境文件统一收纳在 env/ 目录（dev/test/prod 三套模板）
    envDir: './env',
    plugins: [vue()],

    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },

    server: {
      port: 5173,
      host: true,
      // dev 环境免 CORS：/api 反向代理到后端
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: true,
        },
      },
    },

    build: {
      target: 'es2022',
      sourcemap: mode !== 'production',
      chunkSizeWarningLimit: 800,
      rollupOptions: {
        output: {
          manualChunks: {
            vue: ['vue', 'vue-router', 'pinia'],
            element: ['element-plus'],
            markdown: ['markdown-it', 'highlight.js', 'dompurify'],
          },
        },
      },
    },
  }
})
