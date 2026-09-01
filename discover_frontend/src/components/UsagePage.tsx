import type { EChartsCoreOption } from 'echarts/core'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Chart } from '@/components/ui/chart'
import { Skeleton } from '@/components/ui/skeleton'
import { fetchAccountUsage, fetchUsageDaily } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/theme'
import type { AccountUsage, UsageDaily, UsageDailyItem } from '@/types'

/**
 * 用量信息内容区（用户中心左导航「用量」菜单切换进入，非独立页面）：
 * 整体设计模仿用量看板 —— 顶部大值卡片 + 明细卡片 + 按日趋势图（ECharts），按项目主题着色。
 * - 聚合指标：GET /users/me/usage（按 created_by 聚合）；
 * - 趋势图：GET /users/me/usage/daily?days=（接口待后端实现，失败时图区降级为提示）。
 */

/** 趋势图时间窗口选项（近 N 天，切换后重新拉取 /users/me/usage/daily?days=） */
const RANGE_OPTIONS = [7, 30, 90] as const
/** 默认时间窗口（首屏加载用，可在趋势区切换） */
const DEFAULT_RANGE = 30

/** 堆叠段配色：经 dataviz 校验在明暗主题均通过（violet / teal / amber） */
const PALETTE = {
  input: '#0d9488',
  cached: '#d97706',
  output: '#6d5dfb',
}

function formatNumber(value: number): string {
  return value.toLocaleString('zh-CN')
}

/** 用量指标卡：小标签 + 大值（可选单位），对齐看板视觉 */
function UsageStatCard({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="glass-surface rounded-xl border border-border px-5 py-4">
      <p className="text-[13px] text-text-3">{label}</p>
      <p className="mt-2 flex items-baseline gap-1.5">
        <span className="text-2xl font-bold tabular-nums text-text-1">{value}</span>
        {unit !== undefined && <span className="text-[12px] text-text-3">{unit}</span>}
      </p>
    </div>
  )
}

/** 趋势图卡片：标题 + 说明 + 加载 / 失败 / 空态降级 */
function TrendChartCard({
  title,
  description,
  days,
  loading,
  failed,
  option,
}: {
  title: string
  description: string
  days: number
  loading: boolean
  failed: boolean
  option: EChartsCoreOption | null
}) {
  let body: ReactNode
  if (loading) {
    body = (
      <div className="flex h-[272px] items-center justify-center">
        <Skeleton className="h-full w-full" />
      </div>
    )
  } else if (failed) {
    body = (
      <p className="flex h-[272px] items-center justify-center text-[13px] text-text-3">
        趋势数据暂不可用
      </p>
    )
  } else if (option === null) {
    body = (
      <p className="flex h-[272px] items-center justify-center text-[13px] text-text-3">
        近 {days} 天暂无用量数据
      </p>
    )
  } else {
    body = <Chart option={option} />
  }
  return (
    <div className="glass-surface rounded-xl border border-border p-4">
      <h2 className="mb-1 text-sm font-medium text-text-1">{title}</h2>
      <p className="mb-3 text-[12px] text-text-3">{description}</p>
      {body}
    </div>
  )
}

/** 趋势时间范围切换（近 7 / 30 / 90 天，选中态浅色高亮） */
function RangeSwitcher({ days, onChange }: { days: number; onChange: (days: number) => void }) {
  return (
    <fieldset className="m-0 flex min-w-0 items-center gap-0.5 rounded-lg border-0 bg-surface-2 p-0.5">
      <legend className="sr-only">趋势时间范围</legend>
      {RANGE_OPTIONS.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          aria-pressed={days === option}
          className={cn(
            'cursor-pointer rounded-md px-2.5 py-1 text-[12px] transition-colors',
            days === option
              ? 'bg-surface-1 font-medium text-text-1 shadow-sm'
              : 'text-text-3 hover:text-text-1',
          )}
        >
          近 {option} 天
        </button>
      ))}
    </fieldset>
  )
}

/** 主题感知的坐标轴 / 分隔线颜色（文字用 text 类 token，勿用系列色） */
function axisStyle(isDark: boolean): { axisColor: string; splitColor: string } {
  return {
    axisColor: isDark ? '#8b90a0' : '#6b7280',
    splitColor: isDark ? 'rgba(255,255,255,0.08)' : 'rgba(23,26,35,0.08)',
  }
}

/** Token 用量趋势：按日堆叠柱（输入未命中缓存 / 命中缓存 / 输出） */
function buildTokenTrendOption(items: UsageDailyItem[], isDark: boolean): EChartsCoreOption {
  const { axisColor, splitColor } = axisStyle(isDark)
  return {
    // bottom 预留图例高度，避免图例压住柱状图
    grid: { left: 8, right: 8, top: 8, bottom: 32, containLabel: true },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: (value: unknown) => formatNumber(Number(value)),
    },
    legend: {
      bottom: 0,
      icon: 'roundRect',
      itemWidth: 10,
      itemHeight: 6,
      itemGap: 16,
      textStyle: { color: axisColor, fontSize: 11 },
    },
    xAxis: {
      type: 'category',
      data: items.map((item) => item.date.slice(5)),
      axisLine: { lineStyle: { color: splitColor } },
      axisTick: { show: false },
      axisLabel: { color: axisColor, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: splitColor } },
      axisLabel: { color: axisColor, fontSize: 11 },
    },
    series: [
      {
        name: '输入（未命中缓存）',
        type: 'bar',
        stack: 'tokens',
        barMaxWidth: 18,
        itemStyle: { color: PALETTE.input },
        data: items.map((item) => Math.max(0, item.prompt_tokens - item.cached_read_tokens)),
      },
      {
        name: '输入（命中缓存）',
        type: 'bar',
        stack: 'tokens',
        barMaxWidth: 18,
        itemStyle: { color: PALETTE.cached },
        data: items.map((item) => item.cached_read_tokens),
      },
      {
        name: '输出',
        type: 'bar',
        stack: 'tokens',
        barMaxWidth: 18,
        itemStyle: { color: PALETTE.output, borderRadius: [4, 4, 0, 0] },
        data: items.map((item) => item.completion_tokens),
      },
    ],
  }
}

/** 消息数趋势：按日面积图 */
function buildMessageTrendOption(items: UsageDailyItem[], isDark: boolean): EChartsCoreOption {
  const { axisColor, splitColor } = axisStyle(isDark)
  return {
    grid: { left: 8, right: 8, top: 8, bottom: 0, containLabel: true },
    tooltip: {
      trigger: 'axis',
      valueFormatter: (value: unknown) => formatNumber(Number(value)),
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: items.map((item) => item.date.slice(5)),
      axisLine: { lineStyle: { color: splitColor } },
      axisTick: { show: false },
      axisLabel: { color: axisColor, fontSize: 11 },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: splitColor } },
      axisLabel: { color: axisColor, fontSize: 11 },
    },
    series: [
      {
        name: '消息数',
        type: 'line',
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: PALETTE.output },
        itemStyle: { color: PALETTE.output },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: isDark ? 'rgba(109,93,251,0.35)' : 'rgba(109,93,251,0.28)' },
              { offset: 1, color: 'rgba(109,93,251,0.02)' },
            ],
          },
        },
        data: items.map((item) => item.message_count),
      },
    ],
  }
}

export function UsagePage() {
  const isDark = useThemeStore((s) => s.isDark)
  const [usage, setUsage] = useState<AccountUsage | null>(null)
  const [daily, setDaily] = useState<UsageDaily | null>(null)
  const [dailyFailed, setDailyFailed] = useState(false)
  const [days, setDays] = useState(DEFAULT_RANGE)

  // 进入页面即拉取聚合用量（与时间范围无关）
  useEffect(() => {
    void fetchAccountUsage()
      .then(setUsage)
      .catch(() => {})
  }, [])

  // 按当前时间范围拉取趋势（切换范围 → 复位加载态 → 重新拉取）
  useEffect(() => {
    setDaily(null)
    setDailyFailed(false)
    void fetchUsageDaily(days)
      .then(setDaily)
      .catch(() => setDailyFailed(true))
  }, [days])

  const handleRangeChange = useCallback((next: number) => {
    setDays(next)
  }, [])

  const tokenOption = useMemo<EChartsCoreOption | null>(
    () =>
      daily !== null && daily.items.length > 0 ? buildTokenTrendOption(daily.items, isDark) : null,
    [daily, isDark],
  )
  const messageOption = useMemo<EChartsCoreOption | null>(
    () =>
      daily !== null && daily.items.length > 0
        ? buildMessageTrendOption(daily.items, isDark)
        : null,
    [daily, isDark],
  )

  const dailyLoading = daily === null && !dailyFailed

  return (
    <div className="mx-auto w-full max-w-[860px] px-4 pb-10 pt-3 sm:px-6">
      <p className="mb-4 text-[12px] text-text-3">所有数据按当前账户聚合统计，可能存在延迟。</p>

      {usage === null ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <>
          {/* 核心指标（大值卡片） */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <UsageStatCard
              label="总 Token"
              value={formatNumber(usage.total_tokens)}
              unit="tokens"
            />
          </div>

          <div className="my-4 border-t border-border" aria-hidden="true" />

          {/* 明细指标 */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <UsageStatCard label="输入 Token" value={formatNumber(usage.prompt_tokens)} />
            <UsageStatCard label="输出 Token" value={formatNumber(usage.completion_tokens)} />
            <UsageStatCard label="缓存读 Token" value={formatNumber(usage.cached_read_tokens)} />
            <UsageStatCard label="缓存写 Token" value={formatNumber(usage.cached_write_tokens)} />
          </div>
        </>
      )}

      {/* 按日趋势图（时间范围可切换） */}
      <div className="mt-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <p className="text-[13px] text-text-3">按日趋势</p>
          <RangeSwitcher days={days} onChange={handleRangeChange} />
        </div>
        <div className="space-y-4">
          <TrendChartCard
            title="Token 用量趋势"
            description={`近 ${days} 天，按日堆叠（输入 / 输出）`}
            days={days}
            loading={dailyLoading}
            failed={dailyFailed}
            option={tokenOption}
          />
          <TrendChartCard
            title="消息数趋势"
            description={`近 ${days} 天，每日消息量`}
            days={days}
            loading={dailyLoading}
            failed={dailyFailed}
            option={messageOption}
          />
        </div>
      </div>
    </div>
  )
}
