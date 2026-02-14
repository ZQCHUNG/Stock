import { defineStore } from 'pinia'
import { ref } from 'vue'
import { portfolioApi, type OpenPositionParams, type ClosePositionParams } from '../api/portfolio'
import { message } from '../utils/discrete'

export const usePortfolioStore = defineStore('portfolio', () => {
  const positions = ref<any[]>([])
  const closed = ref<any[]>([])
  const summary = ref<any>({})
  const health = ref<any>(null)
  const exitAlerts = ref<any[]>([])
  const equityLedger = ref<any>(null)
  const analytics = ref<any>(null)
  const performance = ref<any>(null)
  const briefing = ref<any>(null)
  const stressTest = ref<any>(null)
  const correlation = ref<any>(null)
  const optimalExposure = ref<any>(null)
  const rebalanceSim = ref<any>(null)
  const marketRegime = ref<any>(null)
  const efficientFrontier = ref<any>(null)
  const behavioralAudit = ref<any>(null)
  const rebalancePlan = ref<any>(null)
  const csvImportResult = ref<any>(null)
  const isLoading = ref(false)

  async function load() {
    isLoading.value = true
    try {
      const data = await portfolioApi.list()
      positions.value = data.positions || []
      closed.value = data.closed || []
      summary.value = data.summary || {}
    } catch {
      /* handled by interceptor */
    }
    isLoading.value = false
  }

  async function openPosition(params: OpenPositionParams) {
    const res = await portfolioApi.open(params)
    if (res.ok) {
      message.success(`已建立 ${params.code} 模擬倉位：${params.lots} 張`)
      await load()
    }
    return res
  }

  async function closePosition(id: string, params: ClosePositionParams) {
    const res = await portfolioApi.close(id, params)
    if (res.ok) {
      message.success(`已平倉，損益 $${res.closed?.net_pnl?.toLocaleString() || 0}`)
      await load()
    }
    return res
  }

  async function updatePosition(id: string, params: { stop_loss?: number; trailing_stop?: number; note?: string }) {
    const res = await portfolioApi.update(id, params)
    if (res.ok) {
      message.success('已更新倉位')
      await load()
    }
    return res
  }

  async function deletePosition(id: string) {
    const res = await portfolioApi.delete(id)
    if (res.ok) {
      message.info('已刪除倉位')
      await load()
    }
    return res
  }

  async function loadHealth() {
    try {
      health.value = await portfolioApi.health()
    } catch {
      health.value = null
    }
  }

  async function loadExitAlerts() {
    try {
      exitAlerts.value = await portfolioApi.exitAlerts()
    } catch {
      exitAlerts.value = []
    }
  }

  async function loadEquityLedger() {
    try {
      equityLedger.value = await portfolioApi.equityLedger()
    } catch {
      equityLedger.value = null
    }
  }

  async function loadAnalytics() {
    try {
      analytics.value = await portfolioApi.analytics()
    } catch {
      analytics.value = null
    }
  }

  async function loadPerformance() {
    try {
      performance.value = await portfolioApi.performance()
    } catch {
      performance.value = null
    }
  }

  async function loadBriefing() {
    try {
      briefing.value = await portfolioApi.briefing()
    } catch {
      briefing.value = null
    }
  }

  async function loadStressTest() {
    try {
      stressTest.value = await portfolioApi.stressTest()
    } catch {
      stressTest.value = null
    }
  }

  async function loadCorrelation() {
    try {
      correlation.value = await portfolioApi.correlation()
    } catch {
      correlation.value = null
    }
  }

  async function loadOptimalExposure() {
    try {
      optimalExposure.value = await portfolioApi.optimalExposure()
    } catch {
      optimalExposure.value = null
    }
  }

  async function simulateRebalance(codes: string[]) {
    try {
      rebalanceSim.value = await portfolioApi.simulateRebalance(codes)
    } catch {
      rebalanceSim.value = null
    }
  }

  async function loadMarketRegime() {
    try {
      marketRegime.value = await portfolioApi.marketRegime()
    } catch {
      marketRegime.value = null
    }
  }

  async function loadEfficientFrontier() {
    try {
      efficientFrontier.value = await portfolioApi.efficientFrontier()
    } catch {
      efficientFrontier.value = null
    }
  }

  async function loadBehavioralAudit() {
    try {
      behavioralAudit.value = await portfolioApi.behavioralAudit()
    } catch {
      behavioralAudit.value = null
    }
  }

  async function loadRebalancePlan() {
    try {
      rebalancePlan.value = await portfolioApi.rebalancePlan()
    } catch {
      rebalancePlan.value = null
    }
  }

  async function importCsv(csvText: string) {
    try {
      csvImportResult.value = await portfolioApi.importCsv(csvText)
      if (csvImportResult.value?.ok) {
        message.success(`匯入完成：${csvImportResult.value.imported} 筆成功`)
        await load()
      }
    } catch {
      csvImportResult.value = null
    }
    return csvImportResult.value
  }

  return {
    positions, closed, summary, health, exitAlerts, equityLedger, analytics, performance,
    briefing, stressTest, correlation, optimalExposure, rebalanceSim,
    marketRegime, efficientFrontier, behavioralAudit, rebalancePlan, csvImportResult, isLoading,
    load, openPosition, closePosition, updatePosition, deletePosition,
    loadHealth, loadExitAlerts, loadEquityLedger, loadAnalytics, loadPerformance,
    loadBriefing, loadStressTest, loadCorrelation, loadOptimalExposure, simulateRebalance,
    loadMarketRegime, loadEfficientFrontier, loadBehavioralAudit, loadRebalancePlan, importCsv,
  }
})
