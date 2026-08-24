/**
 * localStorage 封装：统一 disf_ 前缀；写入失败降级为内存态（CLAUDE.md 第 10 节）。
 * 只存会话元数据，不存消息全文。
 */

const STORAGE_PREFIX = 'disf_'

function prefixedKey(key: string): string {
  return `${STORAGE_PREFIX}${key}`
}

/** 对外暴露带前缀的完整 key（供 storage 事件比对等场景） */
export function getPrefixedKey(key: string): string {
  return prefixedKey(key)
}

/** 读取本地 JSON 元数据；缺失 / 损坏返回 fallback */
export function loadFromStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(prefixedKey(key))
    if (raw === null) return fallback
    // 运行时边界：JSON 反序列化
    const parsed: unknown = JSON.parse(raw)
    return parsed as T
  } catch {
    return fallback
  }
}

/** 写入本地元数据；隐私模式 / 配额满降级为内存态，返回是否落盘成功 */
export function saveToStorage<T>(key: string, value: T): boolean {
  try {
    localStorage.setItem(prefixedKey(key), JSON.stringify(value))
    return true
  } catch (error) {
    console.warn(`[persist] 写入失败，降级为内存态：${key}`, error)
    return false
  }
}

export function removeFromStorage(key: string): void {
  try {
    localStorage.removeItem(prefixedKey(key))
  } catch {
    // 移除失败不影响会话功能
  }
}
