import { defineNuxtConfig } from 'nuxt/config'
import { loadEnv } from 'vite'

// 配置驱动：dev 代理目标读 env/ 下的 VITE_PROXY_TARGET（见 CLAUDE.md 第 4 节）
const env = loadEnv(process.env.NODE_ENV || 'development', './env', '')
const apiProxyTarget = env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000'

export default defineNuxtConfig({
  // SPA 模式固定（CLAUDE.md 第 1 节硬约束）：渲染始终在浏览器端，部署保持 nginx 静态托管
  ssr: false,
  compatibilityDate: '2026-08-26',
  modules: ['@pinia/nuxt', '@element-plus/nuxt'],
  elementPlus: {
    // AppIcon 保持手写 SVG，不引入 @element-plus/icons-vue（CLAUDE.md 第 1 节硬约束）
    icon: false,
  },

  // 全局样式顺序沿用原 src/main.ts：EP 明暗 css-vars 之后引入主题令牌，确保覆盖生效
  css: [
    'element-plus/dist/index.css',
    'element-plus/theme-chalk/dark/css-vars.css',
    '~/styles/theme.css',
    '~/styles/main.css',
  ],

  // 注意：Nuxt 不采纳 vite.envDir（实测未将 env/ 注入 import.meta.env）。
  // VITE_* 经各命令 `--dotenv ./env/.env.{development,test,production}` 注入 process.env 后流入
  // import.meta.env（CLAUDE.md 第 4 节：环境文件仍统一收容于 env/，无密钥模板提交）。

  nitro: {
    // dev 环境免 CORS：/api 反向代理到后端（替代原 vite.config.ts server.proxy）。
    // 注意：nitro 的 devProxy 由 h3 按挂载路径 /api 挂载，会把 /api 前缀从 req.url
    // 剥离后再交给 httpxy 转发（详见 h3 app.use 对 layer.route 的 slice），后端收到的
    // 是 /v1/...，与后端 /api/v1 前缀路由不匹配导致 404。故 target 带 /api 路径，
    // httpxy 会 joinURL(target.pathname, req.url) 还原出 /api/v1/...。
    devProxy: {
      '/api': {
        target: `${apiProxyTarget}/api`,
        changeOrigin: true,
      },
    },
  },

  app: {
    head: {
      htmlAttrs: { lang: 'zh-CN' },
      title: 'Discover Chat',
      meta: [{ name: 'referrer', content: 'strict-origin-when-cross-origin' }],
      // 首屏防主题闪白：经典脚本同步执行（CSP 兼容，自托管 public/theme-init.js）
      script: [{ src: '/theme-init.js' }],
    },
  },
})
