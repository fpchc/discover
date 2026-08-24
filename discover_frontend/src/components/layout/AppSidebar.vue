<script setup lang="ts">
import type { ConversationMeta } from '@/api/types'

defineProps<{
  conversations: ConversationMeta[]
  activeId: string
}>()

const emit = defineEmits<{
  new: []
  select: [id: string]
  delete: [id: string]
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
  <aside class="app-sidebar">
    <div class="app-sidebar__header">
      <span class="app-sidebar__brand">Discover</span>
      <el-button type="primary" plain size="small" @click="emit('new')">＋ 新建会话</el-button>
    </div>
    <div class="app-sidebar__body">
      <el-empty v-if="conversations.length === 0" description="暂无会话" :image-size="60" />
      <ul v-else class="app-sidebar__list">
        <li
          v-for="item in conversations"
          :key="item.conversation_id"
          class="app-sidebar__item"
          :class="{ 'is-active': item.conversation_id === activeId }"
          @click="emit('select', item.conversation_id)"
        >
          <span class="app-sidebar__item-title">{{ item.title }}</span>
          <span class="app-sidebar__item-time">{{ formatTime(item.updated_at) }}</span>
          <el-button class="app-sidebar__item-delete" link type="danger" size="small" @click.stop="emit('delete', item.conversation_id)">
            删除
          </el-button>
        </li>
      </ul>
    </div>
  </aside>
</template>

<style scoped>
.app-sidebar {
  display: flex;
  flex-direction: column;
  width: 260px;
  height: 100%;
  border-right: 1px solid var(--el-border-color-light);
  background: var(--el-bg-color);
}
.app-sidebar__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.app-sidebar__brand {
  font-weight: 700;
}
.app-sidebar__body {
  flex: 1;
  overflow-y: auto;
}
.app-sidebar__list {
  list-style: none;
  margin: 0;
  padding: 8px;
}
.app-sidebar__item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 10px;
  border-radius: 6px;
  cursor: pointer;
  position: relative;
}
.app-sidebar__item:hover {
  background: var(--el-fill-color-light);
}
.app-sidebar__item.is-active {
  background: var(--el-color-primary-light-9);
}
.app-sidebar__item-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.app-sidebar__item-time {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--el-text-color-secondary);
}
.app-sidebar__item-delete {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.app-sidebar__item:hover .app-sidebar__item-delete {
  opacity: 1;
}
</style>
