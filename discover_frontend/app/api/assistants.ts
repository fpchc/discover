/**
 * 助手目录接口（API.md §6.1）。
 * GET /assistants — 用户可选的助手清单（聚合：专家 + 内置通用对话），
 * 聊天页加载时拉取一次，供「助手选择器」渲染选项。
 */
import { httpClient } from './client'
import type { AssistantRecord } from './types'

export async function fetchAssistants(): Promise<AssistantRecord[]> {
  const { data } = await httpClient.get<AssistantRecord[]>('/assistants')
  return data
}
