import { defineStore } from 'pinia'
import { ref } from 'vue'
import { reportApi } from '../api/report'
import { message } from '../utils/discrete'

export const useReportStore = defineStore('report', () => {
  const currentReport = ref<any>(null)
  const isGenerating = ref(false)
  const error = ref('')

  async function generate(code: string, periodDays = 730, marketRegime?: string) {
    isGenerating.value = true
    error.value = ''
    try {
      currentReport.value = await reportApi.generate(code, periodDays, marketRegime)
      message.success('報告產生完成')
    } catch (e: any) {
      error.value = e.message
    } finally {
      isGenerating.value = false
    }
  }

  return { currentReport, isGenerating, error, generate }
})
