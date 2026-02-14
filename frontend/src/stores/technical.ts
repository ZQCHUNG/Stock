import { defineStore } from 'pinia'
import { ref } from 'vue'
import { analysisApi } from '../api/analysis'
import { stocksApi, type TimeSeriesData } from '../api/stocks'

export const useTechnicalStore = defineStore('technical', () => {
  const indicators = ref<TimeSeriesData | null>(null)
  const v4Signal = ref<any>(null)
  const v4Enhanced = ref<any>(null)
  const v4SignalsFull = ref<TimeSeriesData | null>(null)
  const supportResistance = ref<any>(null)
  const volumePatterns = ref<any>(null)
  const institutional = ref<TimeSeriesData | null>(null)
  const stockData = ref<TimeSeriesData | null>(null)
  const isLoading = ref(false)
  const error = ref('')

  async function loadAll(code: string) {
    isLoading.value = true
    error.value = ''
    try {
      const [ind, v4s, v4e, sr, vp, inst, sd] = await Promise.all([
        analysisApi.indicators(code, 365, 200),
        analysisApi.v4Signal(code),
        analysisApi.v4Enhanced(code),
        analysisApi.supportResistance(code),
        analysisApi.volumePatterns(code),
        stocksApi.institutional(code, 20).catch(() => ({ dates: [], columns: {} })),
        stocksApi.data(code, 365),
      ])
      indicators.value = ind
      v4Signal.value = v4s
      v4Enhanced.value = v4e
      supportResistance.value = sr
      volumePatterns.value = vp
      institutional.value = inst
      stockData.value = sd
    } catch (e: any) {
      error.value = e.message || '載入失敗'
    } finally {
      isLoading.value = false
    }
  }

  async function loadV4SignalsFull(code: string) {
    try {
      v4SignalsFull.value = await analysisApi.v4SignalsFull(code, 200)
    } catch { /* ignore */ }
  }

  return {
    indicators, v4Signal, v4Enhanced, v4SignalsFull,
    supportResistance, volumePatterns, institutional, stockData,
    isLoading, error, loadAll, loadV4SignalsFull,
  }
})
