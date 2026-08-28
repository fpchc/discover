import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '@/App'

/**
 * 应用冒烟渲染：确认 React 树（App → 侧栏/主区/输入区 + Toaster）可挂载无异常。
 * 挂载期 loadList / loadAssistants / uploadConfig 请求在 jsdom 失败会被各编排层静默捕获。
 */
describe('App 冒烟渲染', () => {
  it('渲染欢迎语、助手胶囊与输入区', () => {
    render(<App />)
    expect(screen.getByRole('heading', { name: /今天，想/ })).toBeTruthy()
    expect(screen.getByRole('button', { name: /选择助手/ })).toBeTruthy()
    expect(screen.getByPlaceholderText(/发送消息/)).toBeTruthy()
    expect(screen.getByText('内容由 AI 生成，请仔细甄别')).toBeTruthy()
  })
})
