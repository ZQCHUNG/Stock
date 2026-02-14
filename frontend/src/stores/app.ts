import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { stocksApi, type StockItem } from '../api/stocks'
import { systemApi } from '../api/system'
import { analysisApi } from '../api/analysis'

export const useAppStore = defineStore('app', () => {
  const currentStockCode = ref('2330')
  const currentStockName = ref('台積電')
  const allStocks = ref<StockItem[]>([])
  const recentStocks = ref<{ code: string; name: string }[]>([])
  const v4Params = ref<Record<string, any>>({})
  const marketRegime = ref<any>(null)
  const isLoadingStocks = ref(false)

  const stockMap = computed(() => {
    const map = new Map<string, StockItem>()
    for (const s of allStocks.value) map.set(s.code, s)
    return map
  })

  function getStockName(code: string): string {
    return stockMap.value.get(code)?.name || code
  }

  async function loadAllStocks() {
    if (allStocks.value.length > 0) return
    isLoadingStocks.value = true
    try {
      allStocks.value = await stocksApi.list()
    } catch (e) {
      console.error('Failed to load stocks', e)
    } finally {
      isLoadingStocks.value = false
    }
  }

  async function loadRecentStocks() {
    try {
      recentStocks.value = await systemApi.recentStocks()
    } catch { /* ignore */ }
  }

  async function selectStock(code: string) {
    currentStockCode.value = code
    currentStockName.value = getStockName(code) || code
    // record recent
    systemApi.addRecentStock(code).catch(() => {})
    // update recent list locally
    recentStocks.value = recentStocks.value.filter((s) => s.code !== code)
    recentStocks.value.unshift({ code, name: currentStockName.value })
    if (recentStocks.value.length > 20) recentStocks.value.length = 20
  }

  async function loadV4Params() {
    try {
      v4Params.value = await systemApi.v4Params()
    } catch { /* ignore */ }
  }

  async function loadMarketRegime() {
    try {
      marketRegime.value = await analysisApi.marketRegime()
    } catch { /* ignore */ }
  }

  return {
    currentStockCode,
    currentStockName,
    allStocks,
    recentStocks,
    v4Params,
    marketRegime,
    isLoadingStocks,
    stockMap,
    getStockName,
    loadAllStocks,
    loadRecentStocks,
    selectStock,
    loadV4Params,
    loadMarketRegime,
  }
})
