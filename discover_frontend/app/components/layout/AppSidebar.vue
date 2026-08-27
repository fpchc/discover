<script setup lang="ts">
import type { AssistantRecord, ConversationRecord } from '@/api/types'
import AppIcon from '@/components/common/AppIcon.vue'
import { useTheme } from '@/composables/useTheme'
import { APP_ENV } from '@/config/env'

/**
 * 豆包式左栏：品牌区 + 新对话（近黑主按钮 + Ctrl+K 提示）+ 「技能与助手」专家列表
 * + 「最近对话」会话列表 + 底部主题切换 / 环境徽标。
 * 纯展示 + emits 上报；「技能与助手」点选 = 新建绑定该专家的工作会话（由 ChatView 编排）。
 */
const props = defineProps<{
  conversations: ConversationRecord[]
  activeId: string
  /** 列表加载中（首次拉取后端 GET /conversations） */
  loading: boolean
  /** 助手目录（专家，GET /assistants；渲染「技能与助手」） */
  assistants: AssistantRecord[]
  /** 助手目录加载中 */
  assistantLoading: boolean
  /** 当前选择的助手（专家 id / 'generic'；高亮「技能与助手」对应项） */
  selectedAssistantId: string
}>()

const emit = defineEmits<{
  new: []
  select: [id: string]
  delete: [id: string]
  /** 桌面折叠侧栏（ChatView 持有 collapsed 状态） */
  collapse: []
  /** 点选专家助手 → 新建绑定该助手的工作会话 */
  'select-assistant': [id: string]
}>()

const theme = useTheme()

function formatTime(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const sameDay = date.toDateString() === new Date().toDateString()
  const hh = `${date.getHours()}`.padStart(2, '0')
  const mm = `${date.getMinutes()}`.padStart(2, '0')
  if (sameDay) return `${hh}:${mm}`
  return `${date.getMonth() + 1}/${date.getDate()}`
}
</script>

<template>
  <aside class="sidebar">
    <header class="sidebar__header">
      <div class="sidebar__brand">
        <span class="sidebar__logo"><AppIcon name="sparkle" :size="15" /></span>
        <span class="sidebar__title">Discover</span>
      </div>
      <el-button
        class="sidebar__collapse"
        link
        circle
        size="small"
        title="收起侧栏"
        @click="emit('collapse')"
      >
        <AppIcon name="panel-left" :size="16" />
      </el-button>
    </header>

    <el-button class="sidebar__new" @click="emit('new')">
      <template #icon><AppIcon name="plus" :size="16" /></template>
      新对话
      <span class="sidebar__new-kbd">Ctrl K</span>
    </el-button>

    <div class="sidebar__body">
      <p class="sidebar__section">技能与助手</p>
      <div v-if="assistantLoading" class="sidebar__section-skeleton">
        <span v-for="n in 2" :key="`skill-${n}`" />
      </div>
      <ul v-else-if="assistants.length > 0" class="sidebar__skills">
        <li
          v-for="item in assistants"
          :key="item.id"
          class="sidebar__skill"
          :class="{ 'is-active': item.id === selectedAssistantId }"
          :title="item.description"
          @click="emit('select-assistant', item.id)"
        >
          <span class="sidebar__skill-icon"><AppIcon name="sparkle" :size="15" /></span>
          <span class="sidebar__skill-name">{{ item.name }}</span>
        </li>
      </ul>

      <p class="sidebar__section">最近对话</p>
      <div v-if="loading" class="sidebar__skeleton">
        <el-skeleton v-for="n in 4" :key="n" animated :rows="1" />
      </div>
      <p v-else-if="conversations.length === 0" class="sidebar__empty">
        暂无会话<br />点击「新对话」开始探索
      </p>
      <ul v-else class="sidebar__list">
        <li
          v-for="item in conversations"
          :key="item.conversation_id"
          class="sidebar__item"
          :class="{ 'is-active': item.conversation_id === activeId }"
          @click="emit('select', item.conversation_id)"
        >
          <span class="sidebar__item-icon"><AppIcon name="chat" :size="15" /></span>
          <span class="sidebar__item-title">{{ item.name }}</span>
          <span class="sidebar__item-time">
            {{ item.dialogue_count }} · {{ formatTime(item.updated_at) }}
          </span>
          <el-button
            class="sidebar__item-delete"
            link
            size="small"
            title="删除会话"
            @click.stop="emit('delete', item.conversation_id)"
          >
            <AppIcon name="trash" :size="14" />
          </el-button>
        </li>
      </ul>
    </div>

    <footer class="sidebar__footer">
      <el-button class="sidebar__theme" link @click="theme.toggle">
        <template #icon>
          <AppIcon :name="theme.isDark ? 'sun' : 'moon'" :size="16" />
        </template>
        {{ theme.isDark ? '浅色模式' : '深色模式' }}
      </el-button>
      <span v-if="APP_ENV !== 'production'" class="sidebar__env">{{ APP_ENV }}</span>
    </footer>
  </aside>
</template>

<style scoped>
.sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-width: 0;
  background: var(--surface-1);
  border-right: 1px solid var(--border-subtle);
}
.sidebar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px 10px;
}
.sidebar__brand {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sidebar__logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border-radius: 8px;
  background: var(--brand-gradient);
  color: #fff;
  box-shadow: var(--glow-brand);
}
.sidebar__title {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.02em;
  background: var(--brand-gradient);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
}
.sidebar__collapse {
  color: var(--text-3);
}
.sidebar__collapse:hover {
  color: var(--text-1);
}

/* 新对话：近黑主按钮 */
.sidebar__new.el-button {
  position: relative;
  margin: 6px 16px 14px;
  width: calc(100% - 32px);
  height: 40px;
  border: none;
  border-radius: 10px;
  background: var(--brand-gradient);
  color: #fff;
  font-weight: 600;
  box-shadow: var(--glow-brand);
  transition:
    transform 0.15s ease,
    box-shadow 0.15s ease,
    filter 0.15s ease;
}
.sidebar__new.el-button:hover {
  transform: translateY(-1px);
  filter: brightness(1.06);
  box-shadow: 0 8px 26px rgba(139, 92, 246, 0.5);
}
.sidebar__new.el-button:active {
  transform: translateY(0);
}
/* 快捷键提示：EP 按钮默认槽有包裹层，用绝对定位右对齐到按钮内侧 */
.sidebar__new-kbd {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  padding: 1px 7px;
  border-radius: 5px;
  background: rgba(255, 255, 255, 0.14);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.03em;
  color: rgba(255, 255, 255, 0.82);
}

.sidebar__body {
  flex: 1;
  overflow-y: auto;
  padding: 0 10px 12px;
}
.sidebar__section {
  margin: 16px 10px 6px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--text-3);
}
.sidebar__section-skeleton {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 2px 10px;
}
.sidebar__section-skeleton > span {
  height: 36px;
  border-radius: 9px;
  background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-1) 50%, var(--surface-2) 75%);
  background-size: 200% 100%;
  animation: theme-shimmer 1.2s ease-in-out infinite;
}

/* ---- 技能与助手 ---- */
.sidebar__skills {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sidebar__skill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 9px;
  cursor: pointer;
  transition: background-color 0.15s ease;
}
.sidebar__skill:hover {
  background: var(--surface-hover);
}
.sidebar__skill.is-active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.14), rgba(139, 92, 246, 0.08));
}
.sidebar__skill-icon {
  display: inline-flex;
  flex-shrink: 0;
  color: var(--brand-2);
}
.sidebar__skill-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-1);
}

/* ---- 最近对话 ---- */
.sidebar__empty {
  margin: 12px;
  font-size: 13px;
  line-height: 1.7;
  text-align: center;
  color: var(--text-3);
}
.sidebar__skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 12px;
}
.sidebar__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.sidebar__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border-radius: 9px;
  cursor: pointer;
  position: relative;
  transition: background-color 0.15s ease;
}
.sidebar__item:hover {
  background: var(--surface-hover);
}
.sidebar__item.is-active {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.14), rgba(139, 92, 246, 0.08));
}
.sidebar__item.is-active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 22%;
  bottom: 22%;
  width: 3px;
  border-radius: 2px;
  background: var(--brand-gradient);
}
.sidebar__item-icon {
  display: inline-flex;
  flex-shrink: 0;
  color: var(--text-2);
}
.sidebar__item.is-active .sidebar__item-icon {
  color: var(--brand-2);
}
.sidebar__item-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.sidebar__item-time {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-3);
}
.sidebar__item-delete {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s ease;
  color: var(--text-3);
}
.sidebar__item-delete:hover {
  color: var(--el-color-danger);
}
.sidebar__item:hover .sidebar__item-delete {
  opacity: 1;
}

/* ---- 底部 ---- */
.sidebar__footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px 12px;
  border-top: 1px solid var(--border-subtle);
}
.sidebar__theme {
  color: var(--text-2);
  font-size: 13px;
}
.sidebar__theme:hover {
  color: var(--text-1);
}
.sidebar__env {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-3);
  border: 1px solid var(--border-subtle);
  border-radius: 5px;
  padding: 1px 6px;
}

@media (max-width: 767px) {
  .sidebar__collapse {
    display: none;
  }
}
</style>
