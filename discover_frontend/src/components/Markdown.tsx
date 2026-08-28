import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import { Check, Copy } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

// 按需注册语言，控制包体；新增语言在数组追加即可
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('css', css)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('json', json)
hljs.registerLanguage('python', python)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('xml', xml)

/** 代码块复制钮（自身持有 copied 短暂态） */
function CodeCopyButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false)

  async function handleCopy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard 权限被拒时静默（不打断阅读）
    }
  }

  return (
    <button
      type="button"
      title={copied ? '已复制' : '复制代码'}
      onClick={() => void handleCopy()}
      className="code-copy-btn"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  )
}

/**
 * Markdown 渲染组件（CLAUDE.md 第 6 节安全红线）。
 * - react-markdown 默认不渲染原始 HTML（模型输出无法注入 HTML）。
 * - 代码块用 highlight.js 按需高亮，结果经 DOMPurify 清洗后绑定（不可逃逸）。
 * - 流式进行中轻量渲染（不高亮），收尾后启用高亮（performance.md §2 流式渲染降载）。
 * 数据统一在 src/index.css 的 .markdown-body 下。
 */
interface MarkdownProps {
  content: string
  /** 流式进行中：轻量渲染（跳过高亮）；收尾（message_end）后传 false 开启高亮 */
  streaming?: boolean
}

export function Markdown({ content, streaming = false }: MarkdownProps) {
  const components: Components = {
    // 代码块外壳：语言标签头 + 复制钮；流式期不高亮（轻量渲染）
    pre({ node, children }) {
      const first = node?.children?.[0]
      if (first === undefined || first.type !== 'element') {
        return (
          <div className="codeblock">
            <pre>{children}</pre>
          </div>
        )
      }
      const cls = String(first.properties?.className ?? '')
      const match = /language-(\w+)/.exec(cls)
      const lang = match?.[1] ?? ''

      if (streaming) {
        return (
          <div className="codeblock">
            <div className="codeblock-header">
              <span className="codeblock-lang">{lang || 'text'}</span>
            </div>
            <pre>{children}</pre>
          </div>
        )
      }

      // 提取 code 子节点的纯文本（hast 文本节点收窄）
      const text = first.children
        .map((child) => (child.type === 'text' ? child.value : ''))
        .join('')
      const highlighted =
        lang !== '' && hljs.getLanguage(lang)
          ? hljs.highlight(text, { language: lang }).value
          : hljs.highlightAuto(text).value
      return (
        <div className="codeblock">
          <div className="codeblock-header">
            <span className="codeblock-lang">{lang || 'text'}</span>
            <CodeCopyButton code={text} />
          </div>
          <pre>
            <code
              className="hljs"
              // biome-ignore lint/security/noDangerouslySetInnerHtml: 高亮结果已经 DOMPurify.sanitize（安全红线，CLAUDE.md 第 6 节）
              dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(highlighted) }}
            />
          </pre>
        </div>
      )
    },
  }

  return (
    <div className="markdown-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
