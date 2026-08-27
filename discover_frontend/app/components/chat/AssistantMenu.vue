<script setup lang="ts">
import { computed } from 'vue'
import type { AssistantRecord } from '@/api/types'
import AppIcon from '@/components/common/AppIcon.vue'
import { GENERIC_ASSISTANT_ID } from '@/stores/assistants'

/**
 * 输入卡内助手/技能选择器：当前助手胶囊触发钮 + 下拉列表。
 * 列表 = 通用对话（目录外保留项）+ 专家目录（GET /assistants）；
 * 选中写入 Pinia selectedId，随下一次 /chat-messages 绑定 agent_id。
 * 纯展示 + emits 上报，状态由 useAssistantsStore 托管。
 */
const props = defineProps<{
  /** 助手目录（专家，GET /assistants） */
  assistants: AssistantRecord[]
  /** 当前选择（专家 id / 'generic'；空串按通用对话处理） */
  selectedAssistantId: string
  /** 流式中禁用切换 */
  disabled: boolean
}>()

const emit = defineEmits<{
  select: [id: string]
}>()

/** 触发钮图标：通用 → chat，专家 → sparkle */
const triggerIcon = computed<'chat' | 'sparkle'>(() =>
  props.selectedAssistantId === '' || props.selectedAssistantId === GENERIC_ASSISTANT_ID
    ? 'chat'
    : 'sparkle',
)

/** 当前选择展示名（未知 id 兜底为通用对话） */
const selectedName = computed<string>(() => {
  if (props.selectedAssistantId === '' || props.selectedAssistantId === GENERIC_ASSISTANT_ID) {
    return '通用对话'
  }
  const match = props.assistants.find((item) => item.id === props.selectedAssistantId)
  return match?.name ?? '通用对话'
})

/** 下拉选项 = 通用对话 + 专家目录 */
const options = computed<AssistantRecord[]>(() => [
  {
    id: GENERIC_ASSISTANT_ID,
    type: 'generic',
    name: '通用对话',
    description: '日常问答与随手提问',
    capabilities: [],
  },
  ...props.assistants,
])

function handleSelect(command: unknown): void {
  if (props.disabled) return
  // el-dropdown command 为选项值（目录 id / generic 字符串），统一收窄为字符串
  emit('select', String(command))
}
</script>

<template>
  <el-dropdown
    trigger="click"
    placement="top-start"
    :disabled="disabled"
    @command="handleSelect"
  >
    <button
      type="button"
      class="menu"
      :class="{ 'is-disabled': disabled }"
      :title="selectedName"
      :aria-label="`选择助手：${selectedName}`"
    >
      <AppIcon :name="triggerIcon" :size="14" />
      <span class="menu__name">{{ selectedName }}</span>
      <AppIcon name="chevron-down" :size="12" />
    </button>

    <template #dropdown>
      <el-dropdown-menu class="menu__list">
        <el-dropdown-item
          v-for="item in options"
          :key="item.id"
          :command="item.id"
          class="menu__option"
        >
          <span class="menu__item">
            <AppIcon :name="item.type === 'expert' ? 'sparkle' : 'chat'" :size="14" />
            <span class="menu__item-text">
              <span class="menu__item-name">{{ item.name }}</span>
              <span class="menu__item-desc">{{ item.description }}</span>
            </span>
            <AppIcon
              v-if="item.id === selectedAssistantId"
              class="menu__check"
              name="check"
              :size="13"
            />
          </span>
        </el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.menu {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  border: 1px solid var(--border-subtle);
  border-radius: 999px;
  background: var(--surface-2);
  font-size: 12px;
  color: var(--text-2);
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    color 0.15s ease;
}
.menu:hover:not(.is-disabled) {
  border-color: var(--brand-2);
  color: var(--text-1);
}
.menu.is-disabled {
  cursor: not-allowed;
  opacity: 0.7;
}
.menu :deep(svg) {
  color: var(--brand-2);
}
.menu__name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.menu__list {
  min-width: 250px;
}
.menu__item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}
.menu__item :deep(svg) {
  color: var(--brand-2);
  flex-shrink: 0;
}
.menu__item-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
  flex: 1;
}
.menu__item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-1);
}
.menu__item-desc {
  font-size: 12px;
  color: var(--text-3);
}
.menu__check {
  color: var(--brand-2);
  flex-shrink: 0;
}
</style>
