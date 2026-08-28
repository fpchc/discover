import { useEffect, useRef, useState } from 'react'

/**
 * 尾沿节流值（performance.md §2 流式渲染降载）。
 * 高频变化的值（SSE 逐字增量）合并为固定间隔（默认 40ms ≈ 25fps）更新，降低
 * ReactMarkdown 重解析频率；始终保证「最近一次值」在窗口结束时被消费。
 */
export function useThrottledValue<T>(value: T, delayMs = 40): T {
  const [state, setState] = useState<T>(value)
  const latest = useRef<T>(value)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    latest.current = value
    if (timer.current !== null) return
    timer.current = setTimeout(() => {
      timer.current = null
      setState(latest.current)
    }, delayMs)
  }, [value, delayMs])

  useEffect(() => {
    return () => {
      if (timer.current !== null) clearTimeout(timer.current)
    }
  }, [])

  return state
}
