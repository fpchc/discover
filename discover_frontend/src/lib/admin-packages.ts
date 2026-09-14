import type { PackageErrorCategory } from '@/types'

const ERROR_CATEGORY_LABELS: Record<PackageErrorCategory, string> = {
  auth: '鉴权/令牌配置错误',
  billing: '数据源额度/套餐不可用',
  timeout: '执行超时',
  rate_limit: '上游限流',
  connection: '服务连接失败',
  server: '服务端错误',
  invalid_argument: '参数错误',
  not_found: '工具不在目录',
  script: '脚本执行错误',
  config: '配置错误',
  bad_request: '请求参数有误',
  content_filter: '内容被拦截',
  stream_interrupted: '流式响应中断',
  denied: '无权限',
  mcp: 'MCP 工具错误',
  conflict: '状态冲突',
}

/** 冒烟测试 error_category → 前端可读文案（API 文档 §4.2） */
export function errorCategoryLabel(category: PackageErrorCategory | null): string {
  if (category === null) return '无'
  return ERROR_CATEGORY_LABELS[category] ?? category
}

/** ISO-8601 时间格式化为本地可读短时间 */
export function formatPackageTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
