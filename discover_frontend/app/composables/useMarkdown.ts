import DOMPurify from 'dompurify'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import MarkdownIt from 'markdown-it'
// 代码块统一深色面板（明暗双主题一致，GitHub/Vercel 风格）；token 色由该主题提供
import 'highlight.js/styles/github-dark.css'

// 按需注册语言，控制包体；新增语言在数组追加即可
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('python', python)
hljs.registerLanguage('json', json)
hljs.registerLanguage('bash', bash)
hljs.registerLanguage('xml', xml)
hljs.registerLanguage('css', css)

/**
 * highlight 回调返回自绘代码块外壳（语言标签由 CSS ::before + data-lang 呈现）。
 * 返回串以 <pre 开头时 markdown-it 不再包外层；整体经 DOMPurify 清洗（安全红线不变）。
 */
function highlightCode(code: string, lang: string): string {
  const highlighted =
    lang !== '' && hljs.getLanguage(lang)
      ? hljs.highlight(code, { language: lang }).value
      : hljs.highlightAuto(code).value
  const label = lang !== '' ? lang : 'text'
  return `<pre class="codeblock" data-lang="${label}"><code class="hljs">${highlighted}</code></pre>`
}

const markdown = new MarkdownIt({
  // html: false —— 模型输出不解析原始 HTML，仅渲染 markdown 语法（安全收敛）
  html: false,
  linkify: true,
  breaks: true,
  highlight: highlightCode,
})

/**
 * 渲染 Markdown 并强制 DOMPurify 清洗（安全红线，CLAUDE.md 第 6 节）。
 * 调用方绑定 v-html 前必须经过本函数。
 */
export function renderMarkdown(text: string): string {
  const rawHtml = markdown.render(text)
  return DOMPurify.sanitize(rawHtml)
}
