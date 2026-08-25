// 首屏防主题闪白（FOUC）：经典脚本在 <head> 内同步执行，早于首帧绘制。
// 与 useTheme.ts 保持同一存储契约：localStorage['disf_theme'] ∈ light|dark|system。
// 生产 CSP script-src 'self' 放行本文件（自托管经典脚本，非内联）。
;(() => {
  var stored = null
  try {
    stored = localStorage.getItem('disf_theme')
  } catch {
    stored = null
  }
  var dark = false
  if (stored === 'dark') {
    dark = true
  } else if (
    stored !== 'light' &&
    window.matchMedia &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  ) {
    dark = true
  }
  if (dark) {
    document.documentElement.classList.add('dark')
  }
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
})()
