import { defineStore } from 'pinia'
import { ref } from 'vue'
import { backtestApi, type BacktestParams, type BoldBacktestParams, type AggressiveBacktestParams } from '../api/backtest'
import { message } from '../utils/discrete'

export type StrategyType = 'v4' | 'v5' | 'adaptive' | 'bold' | 'aggressive'

const STRATEGY_LABELS: Record<StrategyType, string> = {
  v4: 'V4 趨勢動量',
  v5: 'V5 均值回歸',
  adaptive: 'Adaptive 混合',
  bold: 'Bold 大膽',
  aggressive: 'Aggressive 真大膽',
}

export const useBacktestStore = defineStore('backtest', () => {
  const singleResult = ref<any>(null)
  const singleStrategy = ref<StrategyType>('v4')
  const portfolioResult = ref<any>(null)
  const simulationResult = ref<any>(null)
  const rollingResult = ref<any>(null)
  const sensitivityResult = ref<any>(null)
  const alphaBetaResult = ref<any>(null)
  const boldResult = ref<any>(null)
  const aggressiveResult = ref<any>(null)
  const strategyComparison = ref<any>(null)
  const isLoading = ref(false)
  const error = ref('')

  async function runSingle(code: string, req?: BacktestParams, strategy?: StrategyType) {
    const strat = strategy || singleStrategy.value
    singleStrategy.value = strat
    isLoading.value = true
    error.value = ''
    try {
      let result: any
      switch (strat) {
        case 'v5':
          result = await backtestApi.v5(code, req)
          break
        case 'adaptive':
          result = await backtestApi.adaptive(code, req)
          break
        case 'bold':
          result = await backtestApi.bold(code, { ...req, ultra_wide: true })
          break
        default:
          result = await backtestApi.v4(code, req)
      }
      singleResult.value = result
      message.success(`${STRATEGY_LABELS[strat]} 回測完成：${result.total_trades || 0} 筆交易`)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runPortfolio(codes: string[], req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      portfolioResult.value = await backtestApi.portfolio(codes, req)
      message.success(`組合回測完成：${codes.length} 隻股票`)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runSimulation(code: string, days = 30, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      simulationResult.value = await backtestApi.simulation(code, days, req)
      message.success('模擬交易完成')
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runRolling(code: string, windowMonths = 6, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      rollingResult.value = await backtestApi.rolling(code, windowMonths, req)
      message.success('滾動回測完成')
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runSensitivity(code: string, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      sensitivityResult.value = await backtestApi.sensitivity(code, req)
      message.success('參數敏感度分析完成')
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runAlphaBeta(code: string, req?: BacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      alphaBetaResult.value = await backtestApi.alphaBeta(code, req)
      message.success('Alpha/Beta 分析完成')
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runBold(code: string, req?: BoldBacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      boldResult.value = await backtestApi.bold(code, req)
      message.success(`Bold 回測完成：${boldResult.value.total_trades || 0} 筆交易`)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runAggressive(code: string, req?: AggressiveBacktestParams) {
    isLoading.value = true
    error.value = ''
    try {
      aggressiveResult.value = await backtestApi.aggressive(code, req)
      message.success(`Aggressive 回測完成：${aggressiveResult.value.total_trades || 0} 筆交易`)
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function runStrategyComparison(code: string, req?: { period_days?: number; initial_capital?: number }) {
    isLoading.value = true
    error.value = ''
    try {
      strategyComparison.value = await backtestApi.strategyComparison(code, req)
      message.success('策略比較完成')
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  return {
    singleResult, singleStrategy, portfolioResult, simulationResult, boldResult, aggressiveResult,
    rollingResult, sensitivityResult, alphaBetaResult, strategyComparison,
    isLoading, error,
    runSingle, runPortfolio, runSimulation, runBold, runAggressive,
    runRolling, runSensitivity, runAlphaBeta, runStrategyComparison,
  }
})
