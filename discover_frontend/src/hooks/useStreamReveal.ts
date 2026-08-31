import { useEffect, useRef, useState } from 'react'

// 揭示节奏：每 tick 推进的字符数 / 间隔。reveal 速率 ≈ 5 字/33ms ≈ 151 字/s，
// 高于后端流式 ~66 字/s 的到达率，保证常规流式下揭示不积压（跟随后端逐字），
// 仅在后端末尾一次性 flush 大段时封顶上屏速率，避免大段整块蹦出。
const REVEAL_TICK_MS = 33
const REVEAL_CHARS_PER_TICK = 5

/**
 * 流式正文「打字机」揭示（performance.md §2 流式渲染降载的升级）。
 * 尾沿节流只压缩重解析频率，仍按后端帧粒度整段上屏：后端末尾若一次性下发大段
 * （如 answer 以 100 字整帧 flush），节流无法拆细 → 正文「最后一大段整块出现」。
 * 本 hook 以固定速率逐字符推进「已揭示长度」，把上屏速率封顶在 reveal 速率内：
 * - 后端小帧到达率 < reveal 速率 → 揭示跟随后端，维持打字机节奏；
 * - 后端大帧（末尾整段）→ 揭示按 reveal 速率平滑展开，不再整块蹦出。
 * 揭示在 message_end 后仍继续，直到追上全文；历史消息（挂载即完整）用初值 full 长度直接显示、不重放。
 */
export function useStreamReveal(value: string): string {
  // 初值 = 初始长度：历史消息挂载即完整 → 直接显示；流式消息挂载为空串 → 从 0 揭示
  const [revealedLen, setRevealedLen] = useState(value.length)
  const targetRef = useRef(value)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    targetRef.current = value
    // 目标缩短（非追加的异常路径）防御性收敛
    if (revealedLen > value.length) {
      setRevealedLen(value.length)
      return
    }
    // 未揭示完且未在推进 → 启动 interval（setInterval 自驱动，不依赖逐 tick 重排）
    if (revealedLen < value.length && timerRef.current === null) {
      timerRef.current = setInterval(() => {
        setRevealedLen((prev) => Math.min(prev + REVEAL_CHARS_PER_TICK, targetRef.current.length))
      }, REVEAL_TICK_MS)
    }
  }, [value, revealedLen])

  // 揭示追上全文 → 停 interval（独立 effect，避免在 updater 内做副作用）
  useEffect(() => {
    if (revealedLen >= value.length && timerRef.current !== null) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [value, revealedLen])

  useEffect(() => {
    return () => {
      if (timerRef.current !== null) {
        clearInterval(timerRef.current)
        // StrictMode 开发期 effect 双调用：清理若只 clearInterval 不清空 ref，
        // 二次 effect 因 timerRef 非空而跳过启动 → 揭示冻结在初值。必须同步置空。
        timerRef.current = null
      }
    }
  }, [])

  return value.slice(0, revealedLen)
}
