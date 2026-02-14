import { defineStore } from 'pinia'
import { ref } from 'vue'
import { systemApi } from '../api/system'

export const useCacheStore = defineStore('cache', () => {
  const stats = ref<any>(null)
  const heartbeat = ref<any>(null)

  async function loadStats() {
    try { stats.value = await systemApi.cacheStats() } catch { /* ignore */ }
  }

  async function flush() {
    await systemApi.flushCache()
    await loadStats()
  }

  async function loadHeartbeat() {
    try { heartbeat.value = await systemApi.workerHeartbeat() } catch { /* ignore */ }
  }

  return { stats, heartbeat, loadStats, flush, loadHeartbeat }
})
