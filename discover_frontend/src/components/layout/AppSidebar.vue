<script setup lang="ts">
import type { ConversationMeta } from '@/api/types'
import AppIcon from '@/components/common/AppIcon.vue'

defineProps<{
  conversations: ConversationMeta[]
  activeId: string
}>()

const emit = defineEmits<{
  new: []
  select: [id: string]
  delete: [id: string]
  /** 桌面折叠侧栏（ChatView 持有 collapsed 状态） */
  collapse: []
}>()

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
        <span class="sidebar__logo"><AppIcon name="sparkle" :size="18" /></span>
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

    <el-button class="sidebar__new" type="primary" @click="emit('new')">
      <template #icon><AppIcon name="plus" :size="16" /></template>
      新建会话
    </el-button>

    <div class="sidebar__body">
      <p v-if="conversations.length === 0" class="sidebar__empty">
        暂无会话<br />点击「新建会话」开始探索
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
          <span class="sidebar__item-title">{{ item.title }}</span>
          <span class="sidebar__item-time">{{ formatTime(item.updated_at) }}</span>
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
  padding: 14px 16px 8px;
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
  width: 28px;
  height: 28px;
  border-radius: 9px;
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
.sidebar__new.el-button {
  margin: 8px 16px 12px;
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
.sidebar__body {
  flex: 1;
  overflow-y: auto;
  padding: 0 10px 12px;
}
.sidebar__empty {
  margin: 24px 12px;
  font-size: 13px;
  line-height: 1.7;
  text-align: center;
  color: var(--text-3);
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

@media (max-width: 767px) {
  .sidebar__collapse {
    display: none;
  }
}
</style>
