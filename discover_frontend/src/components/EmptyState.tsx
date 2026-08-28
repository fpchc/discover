import { motion } from 'motion/react'

/**
 * 空态（Discover 原版视觉）：极光背景（aurora blobs）+ 居中 hero
 * 「今天，想探索什么？」（探索 渐变强调）+ 提示行。
 * 助手选择入口收敛到输入卡下拉与侧栏「技能与助手」，空态不再重复卡片列表。
 * 纯展示，不持有对话状态。
 */
export function EmptyState() {
  return (
    <div className="relative flex flex-1 items-center justify-center overflow-hidden">
      <div className="aurora" aria-hidden="true">
        <span className="aurora__blob aurora__blob--1" />
        <span className="aurora__blob aurora__blob--2" />
        <span className="aurora__blob aurora__blob--3" />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="relative z-10 w-full max-w-[640px] px-6 text-center"
      >
        <h1 className="text-[24px] font-bold leading-tight tracking-[0.01em] text-text-1 sm:text-[32px]">
          今天，想<span className="text-brand-gradient">探索</span>什么？
        </h1>
        <p className="mt-3 text-sm text-text-2">在下方输入框选择助手，开始你的探索</p>
      </motion.div>
    </div>
  )
}
