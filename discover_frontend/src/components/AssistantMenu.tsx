import { Check, ChevronDown, MessageSquare, Sparkles } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'
import { GENERIC_ASSISTANT_ID } from '@/stores/assistants'
import type { AssistantRecord } from '@/types'

/**
 * 输入卡内助手/技能选择器：当前助手胶囊触发钮 + 下拉列表。
 * 列表 = 通用对话（目录外保留项）+ 专家目录（GET /assistants）；
 * 选中写入 Zustand selectedId，随下一次 /chat-messages 绑定 agent_id。
 * 纯展示 + 事件上报，状态由 useAssistantsStore 托管。
 */
interface AssistantMenuProps {
  /** 助手目录（专家，GET /assistants） */
  assistants: AssistantRecord[]
  /** 当前选择（专家 id / 'generic'；空串按通用对话处理） */
  selectedAssistantId: string
  /** 流式中禁用切换 */
  disabled: boolean
  onSelect: (id: string) => void
}

export function AssistantMenu({
  assistants,
  selectedAssistantId,
  disabled,
  onSelect,
}: AssistantMenuProps) {
  const isGeneric = selectedAssistantId === '' || selectedAssistantId === GENERIC_ASSISTANT_ID

  /** 当前选择展示名（未知 id 兜底为通用对话） */
  const selectedName = isGeneric
    ? '通用对话'
    : (assistants.find((item) => item.id === selectedAssistantId)?.name ?? '通用对话')

  /** 下拉选项 = 通用对话 + 专家目录 */
  const options: AssistantRecord[] = [
    {
      id: GENERIC_ASSISTANT_ID,
      type: 'generic',
      name: '通用对话',
      description: '日常问答与随手提问',
      capabilities: [],
    },
    ...assistants,
  ]

  function handleSelect(id: string): void {
    if (disabled) return
    onSelect(id)
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild disabled={disabled}>
        <button
          type="button"
          className={cn(
            'inline-flex h-[26px] cursor-pointer items-center gap-1.5 rounded-md px-1 text-[13px] text-text-2 transition-colors hover:text-text-1',
            disabled && 'cursor-not-allowed opacity-70',
          )}
          title={selectedName}
          aria-label={`选择助手：${selectedName}`}
        >
          {isGeneric ? (
            <MessageSquare className="h-3.5 w-3.5 text-brand-2" />
          ) : (
            <Sparkles className="h-3.5 w-3.5 text-brand-2" />
          )}
          <span className="max-w-[120px] truncate">{selectedName}</span>
          <ChevronDown className="h-3 w-3" />
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="min-w-60">
        {options.map((item) => (
          <DropdownMenuItem key={item.id} onSelect={() => handleSelect(item.id)}>
            <span className="flex w-full items-center gap-2">
              {item.type === 'expert' ? (
                <Sparkles className="h-3.5 w-3.5 flex-shrink-0 text-brand-2" />
              ) : (
                <MessageSquare className="h-3.5 w-3.5 flex-shrink-0 text-brand-2" />
              )}
              <span className="flex min-w-0 flex-1 flex-col">
                <span className="text-[13px] font-medium text-text-1">{item.name}</span>
                <span className="text-xs text-text-3">{item.description}</span>
              </span>
              {item.id === selectedAssistantId && (
                <Check className="h-3 w-3 flex-shrink-0 text-brand-2" />
              )}
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
