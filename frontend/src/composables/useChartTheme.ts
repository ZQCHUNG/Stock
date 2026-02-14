import { computed } from 'vue'
import { useThemeStore } from '../stores/theme'

/** Reactive ECharts color palette that follows dark/light mode */
export function useChartTheme() {
  const theme = useThemeStore()

  const colors = computed(() => {
    const dark = theme.isDark
    return {
      // Grid & axis
      splitLine: dark ? '#404040' : '#eee',
      axisLabel: dark ? '#b0b0b0' : '#666',
      legendText: dark ? '#d0d0d0' : '#333',
      // Tooltip
      tooltipBg: dark ? '#2c2c32' : '#fff',
      tooltipBorder: dark ? '#555' : '#ccc',
      tooltipText: dark ? '#e0e0e0' : '#333',
      // Bollinger Bands
      bbLine: dark ? '#888' : '#aaa',
      // Background (for transparent)
      bg: 'transparent',
    }
  })

  /** Tooltip style config for dark/light mode */
  const tooltipStyle = computed(() => ({
    backgroundColor: colors.value.tooltipBg,
    borderColor: colors.value.tooltipBorder,
    textStyle: { color: colors.value.tooltipText, fontSize: 12 },
  }))

  /** Toolbox config with zoom reset + save image */
  const toolboxConfig = computed(() => ({
    show: true,
    right: 10,
    top: 0,
    feature: {
      dataZoom: { yAxisIndex: 'none', title: { zoom: '框選縮放', back: '還原' } },
      restore: { title: '重置' },
      saveAsImage: { title: '存圖', pixelRatio: 2 },
    },
    iconStyle: { borderColor: colors.value.axisLabel },
  }))

  /** Base chart options that should be merged into all chart configs */
  const baseOption = computed(() => ({
    backgroundColor: 'transparent',
    textStyle: { color: colors.value.legendText },
  }))

  return { colors, tooltipStyle, toolboxConfig, baseOption, isDark: computed(() => theme.isDark) }
}
