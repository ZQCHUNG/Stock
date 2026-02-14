import { defineStore } from 'pinia'
import { ref } from 'vue'
import { analysisApi } from '../api/analysis'
import { stocksApi, type TimeSeriesData } from '../api/stocks'

interface TechCacheEntry {
  indicators: TimeSeriesData | null
  v4Signal: any
  v4Enhanced: any
  v4SignalsFull: TimeSeriesData | null
  supportResistance: any
  volumePatterns: any
  institutional: TimeSeriesData | null
  stockData: TimeSeriesData | null
  ts: number
}

const CACHE_TTL = 5 * 60 * 1000 // 5 minutes
const MAX_CACHE = 20

export const useTechnicalStore = defineStore('technical', () => {
  const indicators = ref<TimeSeriesData | null>(null)
  const v4Signal = ref<any>(null)
  const v4Enhanced = ref<any>(null)
  const v4SignalsFull = ref<TimeSeriesData | null>(null)
  const supportResistance = ref<any>(null)
  const volumePatterns = ref<any>(null)
  const institutional = ref<TimeSeriesData | null>(null)
  const stockData = ref<TimeSeriesData | null>(null)
  const adaptiveSignal = ref<any>(null)
  const isLoading = ref(false)
  const error = ref('')

  // Race condition guard: discard stale responses when stock switches mid-flight
  let _loadSeq = 0

  // Cross-page cache: keeps data for previously viewed stocks
  const _cache = new Map<string, TechCacheEntry>()

  function _getCached(code: string): TechCacheEntry | null {
    const entry = _cache.get(code)
    if (!entry) return null
    if (Date.now() - entry.ts > CACHE_TTL) {
      _cache.delete(code)
      return null
    }
    return entry
  }

  function _saveToCache(code: string) {
    if (_cache.size >= MAX_CACHE) {
      let oldest = ''
      let oldestTs = Infinity
      for (const [k, v] of _cache) {
        if (v.ts < oldestTs) { oldest = k; oldestTs = v.ts }
      }
      if (oldest) _cache.delete(oldest)
    }
    _cache.set(code, {
      indicators: indicators.value,
      v4Signal: v4Signal.value,
      v4Enhanced: v4Enhanced.value,
      v4SignalsFull: v4SignalsFull.value,
      supportResistance: supportResistance.value,
      volumePatterns: volumePatterns.value,
      institutional: institutional.value,
      stockData: stockData.value,
      ts: Date.now(),
    })
  }

  async function loadAll(code: string) {
    const seq = ++_loadSeq

    // Clear v4SignalsFull so loadV4SignalsFull won't skip with stale data
    v4SignalsFull.value = null

    // Check cache first — instant switch for previously viewed stocks
    const cached = _getCached(code)
    if (cached) {
      indicators.value = cached.indicators
      v4Signal.value = cached.v4Signal
      v4Enhanced.value = cached.v4Enhanced
      v4SignalsFull.value = cached.v4SignalsFull
      supportResistance.value = cached.supportResistance
      volumePatterns.value = cached.volumePatterns
      institutional.value = cached.institutional
      stockData.value = cached.stockData
      return
    }

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

      // Discard stale response if another loadAll was called while we were fetching
      if (seq !== _loadSeq) return

      indicators.value = ind
      v4Signal.value = v4s
      v4Enhanced.value = v4e
      supportResistance.value = sr
      volumePatterns.value = vp
      institutional.value = inst
      stockData.value = sd

      _saveToCache(code)
    } catch (e: any) {
      if (seq !== _loadSeq) return
      error.value = e.message || '載入失敗'
    } finally {
      if (seq === _loadSeq) isLoading.value = false
    }
  }

  async function loadAdaptiveSignal(code: string) {
    const seq = _loadSeq
    try {
      const data = await analysisApi.adaptiveSignal(code)
      if (seq !== _loadSeq) return
      adaptiveSignal.value = data
    } catch {
      adaptiveSignal.value = null
    }
  }

  async function loadV4SignalsFull(code: string) {
    // v4SignalsFull is cleared in loadAll on stock switch, so this only skips
    // if the data was already restored from cache for the same stock
    if (v4SignalsFull.value) return
    const seq = _loadSeq
    try {
      const data = await analysisApi.v4SignalsFull(code, 200)
      if (seq !== _loadSeq) return // stock changed while fetching
      v4SignalsFull.value = data
      const entry = _cache.get(code)
      if (entry) entry.v4SignalsFull = data
    } catch { /* ignore */ }
  }

  return {
    indicators, v4Signal, v4Enhanced, v4SignalsFull, adaptiveSignal,
    supportResistance, volumePatterns, institutional, stockData,
    isLoading, error, loadAll, loadV4SignalsFull, loadAdaptiveSignal,
  }
})
