<script setup lang="ts">
import { computed } from 'vue'

/**
 * 内联 SVG 图标库（手写，不引入图标依赖——技术栈未列 @element-plus/icons-vue）。
 * 颜色继承 currentColor；sparkle / square 为填充型，其余描边型。
 */

const props = withDefaults(
  defineProps<{
    name:
      | 'sparkle'
      | 'sun'
      | 'moon'
      | 'arrow-up'
      | 'square'
      | 'plus'
      | 'copy'
      | 'chat'
      | 'trash'
      | 'menu'
      | 'chevron-down'
      | 'panel-left'
      | 'paperclip'
      | 'file'
      | 'download'
      | 'external'
      | 'x'
      | 'check'
    size?: number
  }>(),
  { size: 16 },
)

const dimension = computed<string>(() => `${props.size}px`)
</script>

<template>
  <!-- 品牌星芒（填充） -->
  <svg
    v-if="name === 'sparkle'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="currentColor"
    aria-hidden="true"
  >
    <path d="M12 2l2.1 7.9L22 12l-7.9 2.1L12 22l-2.1-7.9L2 12l7.9-2.1z" />
    <path d="M19 3l.7 2.3L22 6l-2.3.7L19 9l-.7-2.3L16 6l2.3-.7z" />
  </svg>

  <!-- 浅色主题（太阳） -->
  <svg
    v-else-if="name === 'sun'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </svg>

  <!-- 深色主题（月亮） -->
  <svg
    v-else-if="name === 'moon'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
  </svg>

  <!-- 发送（上箭头） -->
  <svg
    v-else-if="name === 'arrow-up'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M12 19V5M5 12l7-7 7 7" />
  </svg>

  <!-- 停止（方块，填充） -->
  <svg
    v-else-if="name === 'square'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="currentColor"
    aria-hidden="true"
  >
    <rect x="8" y="8" width="8" height="8" rx="1.5" />
  </svg>

  <!-- 新建（加号） -->
  <svg
    v-else-if="name === 'plus'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    aria-hidden="true"
  >
    <path d="M12 5v14M5 12h14" />
  </svg>

  <!-- 复制 -->
  <svg
    v-else-if="name === 'copy'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <rect x="9" y="9" width="12" height="12" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>

  <!-- 会话（对话气泡） -->
  <svg
    v-else-if="name === 'chat'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>

  <!-- 删除（垃圾桶） -->
  <svg
    v-else-if="name === 'trash'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M3 6h18" />
    <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    <path d="M10 11v6M14 11v6" />
  </svg>

  <!-- 菜单（汉堡） -->
  <svg
    v-else-if="name === 'menu'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    aria-hidden="true"
  >
    <path d="M3 6h18M3 12h18M3 18h18" />
  </svg>

  <!-- 折叠箭头（思考分区） -->
  <svg
    v-else-if="name === 'chevron-down'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M6 9l6 6 6-6" />
  </svg>

  <!-- 附件（回形针） -->
  <svg
    v-else-if="name === 'paperclip'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M21.4 11.1l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6l8.1-8.1" />
  </svg>

  <!-- 文件（文档） -->
  <svg
    v-else-if="name === 'file'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <path d="M14 2v6h6" />
  </svg>

  <!-- 下载 -->
  <svg
    v-else-if="name === 'download'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <path d="M7 10l5 5 5-5M12 15V3" />
  </svg>

  <!-- 新窗口（外链） -->
  <svg
    v-else-if="name === 'external'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    <path d="M15 3h6v6M10 14L21 3" />
  </svg>

  <!-- 关闭（叉） -->
  <svg
    v-else-if="name === 'x'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M18 6L6 18M6 6l12 12" />
  </svg>

  <!-- 选中对勾 -->
  <svg
    v-else-if="name === 'check'"
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path d="M20 6L9 17l-5-5" />
  </svg>

  <!-- 侧栏面板（折叠 / 展开） -->
  <svg
    v-else
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    :width="dimension"
    :height="dimension"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9 4v16" />
  </svg>
</template>
