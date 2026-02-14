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

  /** Base chart options that should be merged into all chart configs */
  const baseOption = computed(() => ({
    backgroundColor: 'transparent',
    textStyle: { color: colors.value.legendText },
  }))

  return { colors, baseOption, isDark: computed(() => theme.isDark) }
}
