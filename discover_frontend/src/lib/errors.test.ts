import { AxiosError } from 'axios'
import { describe, expect, it } from 'vitest'
import {
  mapHttpError,
  mapSseError,
  readResponseError,
  STREAM_INTERRUPTED,
  TIMEOUT_ERROR,
} from '@/lib/errors'

describe('mapSseError', () => {
  it('解析合法 error 帧', () => {
    const err = mapSseError({ status: 429, code: 'RATE_LIMITED', message: '太频繁' })
    expect(err).toEqual({ status: 429, code: 'RATE_LIMITED', message: '太频繁' })
  })

  it('载荷非对象回退默认文案', () => {
    expect(mapSseError('oops')).toEqual({
      status: null,
      code: 'SSE_ERROR',
      message: '流式响应异常',
    })
  })

  it('字段缺失时逐项兜底', () => {
    const err = mapSseError({})
    expect(err).toEqual({ status: null, code: 'SSE_ERROR', message: '流式响应异常' })
  })
})

describe('mapHttpError', () => {
  it('axios 带状态码 → 状态文案', () => {
    const axiosError = new AxiosError('Request failed', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 404,
      statusText: 'Not Found',
      headers: {},
      config: {},
      data: { detail: '会话不存在或已失效' },
    } as never)
    expect(mapHttpError(axiosError).message).toBe('会话不存在或已失效')
  })

  it('axios 无响应（网络断）→ 网络文案', () => {
    const axiosError = new AxiosError('Network Error', 'ERR_NETWORK')
    expect(mapHttpError(axiosError)).toEqual({
      status: null,
      code: 'NETWORK_ERROR',
      message: '网络请求失败，请稍后重试',
    })
  })

  it('PlatformError 形状 {error:{message}} 优先取后端文案', () => {
    const axiosError = new AxiosError('', 'ERR_BAD_REQUEST', undefined, undefined, {
      status: 500,
      statusText: 'Internal',
      headers: {},
      config: {},
      data: { error: { category: 'platform', message: '模型服务异常' } },
    } as never)
    expect(mapHttpError(axiosError).message).toBe('模型服务异常')
  })

  it('原生 Error → 用其 message', () => {
    expect(mapHttpError(new Error('boom'))).toEqual({
      status: null,
      code: 'NETWORK_ERROR',
      message: 'boom',
    })
  })

  it('未知值 → 默认网络文案', () => {
    expect(mapHttpError(42)).toEqual({
      status: null,
      code: 'UNKNOWN_ERROR',
      message: '网络请求失败，请稍后重试',
    })
  })
})

describe('readResponseError', () => {
  it('从非 2xx 响应解析错误体', async () => {
    const response = new Response(JSON.stringify({ detail: '参数有误' }), {
      status: 422,
      headers: { 'Content-Type': 'application/json' },
    })
    const error = await readResponseError(response)
    expect(error.appError.status).toBe(422)
    expect(error.appError.message).toBe('参数有误')
  })

  it('非 JSON 响应体回退状态码兜底文案', async () => {
    const response = new Response('plain text', { status: 500 })
    const error = await readResponseError(response)
    expect(error.appError.message).toBe('服务内部错误')
  })
})

describe('常量错误', () => {
  it('STREAM_INTERRUPTED 语义：保留已收内容', () => {
    expect(STREAM_INTERRUPTED.code).toBe('STREAM_INTERRUPTED')
  })

  it('TIMEOUT_ERROR 语义：响应超时', () => {
    expect(TIMEOUT_ERROR.code).toBe('TIMEOUT')
  })
})
