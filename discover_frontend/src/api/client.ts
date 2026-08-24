import axios from 'axios'
import { API_BASE_URL, REQUEST_TIMEOUT_MS } from '@/config/env'

/** 普通 HTTP（blocking 模式）统一出口；SSE 不经过此实例（见 api/chat.ts） */
export const httpClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: REQUEST_TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json' },
})
