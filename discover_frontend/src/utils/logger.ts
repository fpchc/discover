/**
 * 统一结构化日志出口 + 全局错误边界。
 * 前端仅消费现有 API；此处预留远程上报接入点（后续可经现有接口上报）。
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

const LEVEL_PREFIX: Record<LogLevel, string> = {
  debug: '[DEBUG]',
  info: '[INFO]',
  warn: '[WARN]',
  error: '[ERROR]',
}

function log(level: LogLevel, ...args: unknown[]): void {
  const prefix = `[discover]${LEVEL_PREFIX[level]}`
  if (level === 'error') {
    console.error(prefix, ...args)
  } else if (level === 'warn') {
    console.warn(prefix, ...args)
  } else if (level === 'info') {
    console.info(prefix, ...args)
  } else {
    console.debug(prefix, ...args)
  }
}

export const logger = {
  debug: (...args: unknown[]) => log('debug', ...args),
  info: (...args: unknown[]) => log('info', ...args),
  warn: (...args: unknown[]) => log('warn', ...args),
  error: (...args: unknown[]) => log('error', ...args),
}

function reportUnhandled(error: unknown, context: string): void {
  logger.error(`[global:${context}]`, error)
}

/** 全局错误边界：捕获未处理异常与 Promise rejection，统一记录 */
export function setupGlobalErrorHandler(): void {
  window.addEventListener('error', (event) => {
    reportUnhandled(event.error ?? event.message, 'error')
  })
  window.addEventListener('unhandledrejection', (event) => {
    reportUnhandled(event.reason, 'unhandledrejection')
  })
}
