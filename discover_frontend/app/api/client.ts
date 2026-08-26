import axios from 'axios'
import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '@/config/env'

/**
 * 普通 HTTP（blocking 模式）统一出口；SSE 不经过此实例（见 api/chat.ts）。
 * 注意：不得在实例默认头里写死 Content-Type —— axios 会据此对 FormData 做
 * JSON.stringify(formDataToJSON(data))，导致文件上传变成 JSON 体、后端 422。
 * 让 axios 按请求体自动推断：JSON 对象 → application/json，FormData → 浏览器补 multipart。
 */
export const httpClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
})
