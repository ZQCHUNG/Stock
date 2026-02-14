import { defineStore } from 'pinia'
import { ref } from 'vue'
import { watchlistApi } from '../api/watchlist'
import { fetchSSE, type SSEProgress } from '../composables/useSSE'
import { message } from '../utils/discrete'

export const useWatchlistStore = defineStore('watchlist', () => {
  const watchlist = ref<{ code: string; name: string }[]>([])
  const overview = ref<any[]>([])
  const batchResults = ref<any[]>([])
  const isLoading = ref(false)
  const batchProgress = ref<SSEProgress>({ current: 0, total: 0, message: '' })

  async function load() {
    try {
      watchlist.value = await watchlistApi.get()
    } catch { /* interceptor handles toast */ }
  }

  async function add(code: string) {
    try {
      await watchlistApi.add(code)
      await load()
      message.success(`已加入自選股: ${code}`)
    } catch { /* interceptor handles toast */ }
  }

  async function remove(code: string) {
    try {
      await watchlistApi.remove(code)
      await load()
      message.success(`已移除自選股: ${code}`)
    } catch { /* interceptor handles toast */ }
  }

  async function loadOverview() {
    isLoading.value = true
    try {
      overview.value = await watchlistApi.overview()
    } catch { /* interceptor handles toast */ }
    finally { isLoading.value = false }
  }

  async function runBatchBacktest(req?: any) {
    isLoading.value = true
    batchProgress.value = { current: 0, total: 0, message: '' }
    try {
      const result = await fetchSSE<any[]>(
        '/api/watchlist/batch-backtest-stream',
        req || {},
        {
          onProgress: (p) => { batchProgress.value = p },
          onDone: (r) => { batchResults.value = r },
          onError: (msg) => { message.error(`批次回測失敗: ${msg}`) },
        },
      )
      if (result) {
        batchResults.value = result
        message.success(`批次回測完成：${result.length} 隻`)
      }
    } catch (e: any) {
      message.error(`批次回測失敗: ${e.message}`)
    } finally {
      isLoading.value = false
      batchProgress.value = { current: 0, total: 0, message: '' }
    }
  }

  return { watchlist, overview, batchResults, isLoading, batchProgress, load, add, remove, loadOverview, runBatchBacktest }
})
