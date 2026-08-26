<script setup lang="ts">
import { computed } from 'vue'
import type { AssistantRecord } from '@/api/types'
import AppIcon from '@/components/common/AppIcon.vue'

/**
 * 助手选择器（API.md §6）：用户在专家 / 通用对话间显式选择。
 * 选择随下一次 /chat-messages 生效（首轮绑定 / 续聊切换），
 * 由 useChatStream 读取 store 的 selectedId 带上 agent_id。
 * 纯展示 + emits 上报，状态由 useAssistantsStore 托管。
 */
const props = defineProps<{
  /** 助手目录（含专家 + 通用对话；空目录时渲染静态通用兜底） */
  catalog: AssistantRecord[]
  /** 当前选择（专家 id / 'generic'；目录未加载前为空串） */
  selectedId: string
  /** 目录加载中 */
  loading: boolean
  /** 流式中禁用选择 */
  disabled: boolean
}>()

const emit = defineEmits<{
  change: [id: string]
}>()

/** 当前选择项展示名（未知 id 兜底为通用对话） */
const selectedName = computed<string>(() => {
  const match = props.catalog.find((item) => item.id === props.selectedId)
  return match?.name ?? '通用对话'
})

function handleChange(value: unknown): void {
  // 单选值为目录 id（string）；兜底转字符串（不设 clearable，不会出现空值）
  emit('change', String(value))
}
</script>

<template>
  <div class="picker">
    <el-select
      v-if="catalog.length > 0"
      class="picker__select"
      :model-value="selectedId"
      :disabled="disabled"
      :title="selectedName"
      placeholder="选择助手"
      size="small"
      @update:model-value="handleChange"
    >
      <template #prefix>
        <AppIcon name="sparkle" :size="13" />
      </template>
      <el-option
        v-for="item in catalog"
        :key="item.id"
        :label="item.name"
        :value="item.id"
      >
        <div class="picker__option">
          <span class="picker__option-name">{{ item.name }}</span>
          <span class="picker__option-desc">{{ item.description }}</span>
        </div>
      </el-option>
    </el-select>
    <span v-else class="picker__fallback" :title="loading ? '加载中…' : '通用对话'">
      <AppIcon name="sparkle" :size="13" />
      <span>{{ loading ? '加载助手…' : '通用对话' }}</span>
    </span>
  </div>
</template>

<style scoped>
.picker {
  display: inline-flex;
  flex-shrink: 0;
}
.picker__select {
  /* EP 2.9 支持 --el-select-width 控制宽度 */
  --el-select-width: 140px;
  color: var(--text-2);
  font-size: 12px;
}
.picker__select :deep(.el-select__wrapper) {
  border-radius: 999px;
  background: var(--surface-2);
}
.picker__fallback {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  border: 1px solid var(--border-subtle);
  background: var(--surface-2);
  font-size: 12px;
  color: var(--text-3);
  white-space: nowrap;
}
.picker__fallback :deep(svg) {
  color: var(--brand-2);
}
.picker__option {
  display: flex;
  flex-direction: column;
  line-height: 1.4;
}
.picker__option-name {
  font-size: 13px;
  font-weight: 600;
}
.picker__option-desc {
  font-size: 12px;
  color: var(--text-3);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 767px) {
  .picker__select {
    --el-select-width: 116px;
  }
  .picker__option-desc {
    display: none;
  }
}
</style>
