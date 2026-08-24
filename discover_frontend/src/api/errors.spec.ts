import { describe, expect, it } from 'vitest'
import {
  HttpError,
  mapHttpError,
  mapSseError,
  readResponseError,
  STREAM_INTERRUPTED,
  TIMEOUT_ERROR,
} from './errors'

describe('mapHttpError', () => {
  it('axios 带状态码：优先取错误体文案', () => {
    const error = {
      isAxiosError: true,
      response: {
        status: 400,
        data: { error: { category: 'bad_request', message: 'query 过长' } },
      },
    }
    expect(mapHttpError(error)).toEqual({ status: 400, code: 'HTTP_400', message: 'query 过长' })
  })

  it('axios 带状态码无错误体：按状态码兜底文案', () => {
    const error = { isAxiosError: true, response: { status: 404, data: {} } }
    expect(mapHttpError(error)).toEqual({
      status: 404,
      code: 'HTTP_404',
      message: '会话不存在或已失效',
    })
  })

  it('axios 网络错误（无响应）：映射 NETWORK_ERROR', () => {
    const error = { isAxiosError: true }
    expect(mapHttpError(error)).toEqual({
      status: null,
      code: 'NETWORK_ERROR',
      message: '网络请求失败，请稍后重试',
    })
  })

  it('原生 Error 映射 NETWORK_ERROR', () => {
    expect(mapHttpError(new Error('boom'))).toEqual({
      status: null,
      code: 'NETWORK_ERROR',
      message: 'boom',
    })
  })

  it('未知异常映射 UNKNOWN_ERROR', () => {
    expect(mapHttpError(null)).toEqual({
      status: null,
      code: 'UNKNOWN_ERROR',
      message: '网络请求失败，请稍后重试',
    })
  })
})

describe('mapSseError', () => {
  it('收窄错误帧字段', () => {
    expect(mapSseError({ status: 429, code: 'rate_limit', message: 'too many' })).toEqual({
      status: 429,
      code: 'rate_limit',
      message: 'too many',
    })
  })

  it('非对象输入使用默认文案', () => {
    expect(mapSseError(null)).toEqual({ status: null, code: 'SSE_ERROR', message: '流式响应异常' })
  })
})

describe('readResponseError', () => {
  it('解析 {error:{category,message}} 错误体', async () => {
    const response = new Response(
      JSON.stringify({ error: { category: 'bad_request', message: '参数有误' } }),
      { status: 400 },
    )
    const httpError = await readResponseError(response)
    expect(httpError).toBeInstanceOf(HttpError)
    expect(httpError.appError).toEqual({ status: 400, code: 'HTTP_400', message: '参数有误' })
  })

  it('解析 {detail} 错误体', async () => {
    const response = new Response(JSON.stringify({ detail: 'Not Found' }), { status: 404 })
    const httpError = await readResponseError(response)
    expect(httpError.appError.message).toBe('Not Found')
  })

  it('非 JSON body 使用状态码兜底文案', async () => {
    const response = new Response('Bad Gateway', { status: 502 })
    const httpError = await readResponseError(response)
    expect(httpError.appError.message).toBe('网关错误，请稍后重试')
  })
})

describe('常量错误', () => {
  it('STREAM_INTERRUPTED / TIMEOUT_ERROR 语义固定', () => {
    expect(STREAM_INTERRUPTED.code).toBe('STREAM_INTERRUPTED')
    expect(TIMEOUT_ERROR.code).toBe('TIMEOUT')
  })
})
