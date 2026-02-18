import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  clusterApi,
  type DualSimilarResult,
  type FeatureStatus,
} from '../api/cluster'

export const useClusterStore = defineStore('cluster', () => {
  // --- State ---
  const queryDate = ref<string | null>(null)  // null = latest
  const topK = ref(30)
  const excludeSelf = ref(true)

  const result = ref<DualSimilarResult | null>(null)
  const featureStatus = ref<FeatureStatus | null>(null)
  const isLoading = ref(false)
  const error = ref('')

  // --- Actions ---

  async function loadFeatureStatus() {
    try {
      featureStatus.value = await clusterApi.featureStatus()
    } catch (e) {
      console.error('Failed to load feature status:', e)
    }
  }

  async function loadSimilarDual(stockCode: string) {
    if (!stockCode) return

    isLoading.value = true
    error.value = ''
    result.value = null

    try {
      result.value = await clusterApi.similarDual({
        stock_code: stockCode,
        query_date: queryDate.value,
        top_k: topK.value,
        exclude_self: excludeSelf.value,
      })
    } catch (e: any) {
      error.value = e.message || String(e)
    } finally {
      isLoading.value = false
    }
  }

  return {
    // State
    queryDate,
    topK,
    excludeSelf,
    result,
    featureStatus,
    isLoading,
    error,
    // Actions
    loadFeatureStatus,
    loadSimilarDual,
  }
})
