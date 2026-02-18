import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  clusterApi,
  type DualSimilarResult,
  type FeatureStatus,
  type DimensionInfo,
} from '../api/cluster'

export const useClusterStore = defineStore('cluster', () => {
  // --- State ---
  const queryDate = ref<string | null>(null)  // null = latest
  const topK = ref(30)
  const excludeSelf = ref(true)
  const selectedDimensions = ref<string[]>([])  // R88.3: empty = all

  const result = ref<DualSimilarResult | null>(null)
  const featureStatus = ref<FeatureStatus | null>(null)
  const dimensions = ref<DimensionInfo[]>([])
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

  async function loadDimensions() {
    try {
      const resp = await clusterApi.dimensions()
      dimensions.value = resp.dimensions
      // Default: all selected
      if (selectedDimensions.value.length === 0) {
        selectedDimensions.value = resp.dimensions.map(d => d.name)
      }
    } catch (e) {
      console.error('Failed to load dimensions:', e)
    }
  }

  async function loadSimilarDual(stockCode: string) {
    if (!stockCode) return

    isLoading.value = true
    error.value = ''
    result.value = null

    // If all dims selected, send null (= all)
    const allNames = dimensions.value.map(d => d.name)
    const dimsParam =
      selectedDimensions.value.length === 0 ||
      selectedDimensions.value.length === allNames.length
        ? null
        : selectedDimensions.value

    try {
      result.value = await clusterApi.similarDual({
        stock_code: stockCode,
        query_date: queryDate.value,
        top_k: topK.value,
        exclude_self: excludeSelf.value,
        dimensions: dimsParam,
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
    selectedDimensions,
    result,
    featureStatus,
    dimensions,
    isLoading,
    error,
    // Actions
    loadFeatureStatus,
    loadDimensions,
    loadSimilarDual,
  }
})
