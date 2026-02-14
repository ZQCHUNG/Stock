import { defineStore } from 'pinia'
import { ref } from 'vue'
import { watchlistApi } from '../api/watchlist'
import { fetchSSE, type SSEProgress } from '../composables/useSSE'

export const useWatchlistStore = defineStore('watchlist', () => {
  const watchlist = ref<{ code: string; name: string }[]>([])
  const overview = ref<any[]>([])
  const batchResults = ref<any[]>([])
  const isLoading = ref(false)
  const batchProgress = ref<SSEProgress>({ current: 0, total: 0, message: '' })

  async function load() {
    try {
      watchlist.value = await watchlistApi.get()
    } catch { /* ignore */ }
  }

  async function add(code: string) {
    await watchlistApi.add(code)
    await load()
  }

  async function remove(code: string) {
    await watchlistApi.remove(code)
    await load()
  }

  async function loadOverview() {
    isLoading.value = true
    try {
      overview.value = await watchlistApi.overview()
    } catch { /* ignore */ }
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
        },
      )
      if (result) batchResults.value = result
    } catch { /* ignore */ }
    finally {
      isLoading.value = false
      batchProgress.value = { current: 0, total: 0, message: '' }
    }
  }

  return { watchlist, overview, batchResults, isLoading, batchProgress, load, add, remove, loadOverview, runBatchBacktest }
})
