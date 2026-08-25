import ElementPlus from 'element-plus'
import { createPinia } from 'pinia'
import { createApp } from 'vue'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import App from './App.vue'
import router from './router'
import { setupGlobalErrorHandler } from './utils/logger'
// 主题令牌须在 EP 明暗 css-vars 之后引入，确保覆盖生效
import './styles/theme.css'
import './styles/main.css'

setupGlobalErrorHandler()

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(ElementPlus)

app.mount('#app')
