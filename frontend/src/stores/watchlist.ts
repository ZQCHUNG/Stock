import { defineStore } from 'pinia'
import { ref } from 'vue'
import { watchlistApi } from '../api/watchlist'

export const useWatchlistStore = defineStore('watchlist', () => {
  const watchlist = ref<{ code: string; name: string }[]>([])
  const overview = ref<any[]>([])
  const batchResults = ref<any[]>([])
  const isLoading = ref(false)

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
    try {
      batchResults.value = await watchlistApi.batchBacktest(req)
    } catch { /* ignore */ }
    finally { isLoading.value = false }
  }

  return { watchlist, overview, batchResults, isLoading, load, add, remove, loadOverview, runBatchBacktest }
})
