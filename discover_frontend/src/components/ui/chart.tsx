import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import type { EChartsCoreOption, EChartsType } from 'echarts/core'
import * as echarts from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { useEffect, useRef } from 'react'

// echarts 按需装配（bar / line + grid / tooltip / legend + canvas），避免全量引入。
// 说明：chart 库为满足「用量信息尽量用图展示」新增（CLAUDE.md §1 硬约束逃逸，用户明确指示）。
echarts.use([BarChart, LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

interface ChartProps {
  option: EChartsCoreOption
  /** 图表高度（px）；宽度自适应容器 */
  height?: number
}

/**
 * echarts 轻封装：挂载初始化 / 卸载 dispose / option 变更 setOption / 容器尺寸变化 resize。
 * 纯渲染层，不持有业务状态；图表颜色 / 轴样式由调用方按主题传入 option。
 */
export function Chart({ option, height = 272 }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<EChartsType | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (el === null) return
    const chart = echarts.init(el)
    chartRef.current = chart
    return () => {
      chart.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    chartRef.current?.setOption(option, true)
  }, [option])

  useEffect(() => {
    const el = containerRef.current
    if (el === null || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => {
      chartRef.current?.resize()
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  return <div ref={containerRef} style={{ height }} />
}
