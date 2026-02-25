import client from './client'

export interface BacktestParams {
  period_days?: number
  initial_capital?: number
  params?: Record<string, any>
  commission_rate?: number
  tax_rate?: number
  slippage?: number
}

export interface BoldBacktestParams {
  period_days?: number
  initial_capital?: number
  params?: Record<string, any>
  ultra_wide?: boolean
  commission_rate?: number
  tax_rate?: number
  slippage?: number
  broker_discount?: number  // Phase 9A: 1.0=full, 0.28=2.8折
  use_dynamic_slippage?: boolean  // Phase 9A: Kyle Lambda
}

export interface AggressiveBacktestParams {
  period_days?: number
  initial_capital?: number
  params?: Record<string, any>
  commission_rate?: number
  tax_rate?: number
  slippage?: number
}

export interface StrategyComparisonParams {
  period_days?: number
  initial_capital?: number
  v4_params?: Record<string, any>
  v5_params?: Record<string, any>
}

export const backtestApi = {
  v4: (code: string, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/v4`, req),
  v5: (code: string, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/v5`, req),
  adaptive: (code: string, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/adaptive`, req),
  portfolio: (stockCodes: string[], req: BacktestParams = {}) =>
    client.post<any, any>('/backtest/portfolio', { stock_codes: stockCodes, ...req }),
  simulation: (code: string, days = 30, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/simulation`, { days, ...req }),
  rolling: (code: string, windowMonths = 6, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/rolling`, { window_months: windowMonths, ...req }),
  sensitivity: (code: string, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/sensitivity`, req),
  alphaBeta: (code: string, req: BacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/alpha-beta`, req),
  bold: (code: string, req: BoldBacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/bold`, req, { timeout: 120_000 }),
  aggressive: (code: string, req: AggressiveBacktestParams = {}) =>
    client.post<any, any>(`/backtest/${code}/aggressive`, req, { timeout: 180_000 }),
  strategyComparison: (code: string, req: StrategyComparisonParams = {}) =>
    client.post<any, any>(`/backtest/${code}/strategy-comparison`, req),
  portfolioBold: (periodDays = 1095, initialCapital = 10_000_000, params?: Record<string, any>, brokerDiscount = 1.0, useDynamicSlippage = false) =>
    client.post<any, any>('/backtest/portfolio-bold', {
      period_days: periodDays,
      initial_capital: initialCapital,
      params,
      broker_discount: brokerDiscount,
      use_dynamic_slippage: useDynamicSlippage,
    }, { timeout: 600_000 }),
  metaStrategy: (stockCodes: string[], periodDays = 730, initialCapital = 1_000_000) =>
    client.post<any, any>('/backtest/meta-strategy', {
      stock_codes: stockCodes,
      period_days: periodDays,
      initial_capital: initialCapital,
    }, { timeout: 300_000 }),
  sqsBacktest: (stockCodes?: string[], periodDays = 730, thresholds = [40, 60, 80]) =>
    client.post<any, any>('/backtest/sqs-backtest', {
      stock_codes: stockCodes || null,
      period_days: periodDays,
      thresholds,
      max_workers: 4,
    }, { timeout: 600_000 }),

  // Phase 10A: Rolling WFA
  rollingWfa: (windowMonths = 3, brokerDiscount = 0.28, useDynamicSlippage = true) =>
    client.post<any, any>('/backtest/rolling-wfa', {
      window_months: windowMonths,
      broker_discount: brokerDiscount,
      use_dynamic_slippage: useDynamicSlippage,
    }, { timeout: 600_000 }),

  // Phase 10C: Attribution Analysis
  attributionAnalysis: (windowMonths = 3, brokerDiscount = 0.28, useDynamicSlippage = true) =>
    client.post<any, any>('/backtest/attribution-analysis', {
      window_months: windowMonths,
      broker_discount: brokerDiscount,
      use_dynamic_slippage: useDynamicSlippage,
    }, { timeout: 600_000 }),

  // Phase 11: Regime Barometer
  regimeBarometer: (lookbackDays = 180, tradeWindow = 20) =>
    client.post<any, any>('/backtest/regime-barometer', {
      lookback_days: lookbackDays,
      trade_window: tradeWindow,
    }, { timeout: 300_000 }),

  // Phase 12: Adaptive Sniper A/B Comparison
  adaptiveSniperAB: (periodDays = 1095, brokerDiscount = 0.28, useDynamicSlippage = true) =>
    client.post<any, any>('/backtest/adaptive-sniper-ab', {
      period_days: periodDays,
      initial_capital: 10_000_000,
      broker_discount: brokerDiscount,
      use_dynamic_slippage: useDynamicSlippage,
    }, { timeout: 600_000 }),

  // R59: Forward Testing
  forwardTestSummary: () =>
    client.get<any, any>('/backtest/forward-test/summary'),
  forwardTestSignals: (limit = 50, status?: string) =>
    client.get<any, any>('/backtest/forward-test/signals', { params: { limit, status } }),
  forwardTestPositions: (limit = 50, status?: string) =>
    client.get<any, any>('/backtest/forward-test/positions', { params: { limit, status } }),
  forwardTestScan: (stockCodes?: string[]) =>
    client.post<any, any>('/backtest/forward-test/scan', stockCodes, { timeout: 120_000 }),
  forwardTestOpen: (signalId: number, capital = 500_000) =>
    client.post<any, any>(`/backtest/forward-test/open/${signalId}`, null, { params: { capital } }),
  forwardTestUpdate: () =>
    client.post<any, any>('/backtest/forward-test/update'),
  forwardTestCompare: (stockCode?: string) =>
    client.get<any, any>('/backtest/forward-test/compare', { params: { stock_code: stockCode } }),

  // R60: Risk Management
  riskAssess: (params: {
    stock_codes?: string[]
    portfolio_value?: number
    holdings?: Record<string, number>
    confidence?: number
    daily_pnl?: number
    weekly_pnl?: number
    monthly_pnl?: number
    consecutive_losses?: number
  }) => client.post<any, any>('/backtest/risk/assess', params, { timeout: 60_000 }),
  riskVar: (params: {
    stock_codes?: string[]
    portfolio_value?: number
    holdings?: Record<string, number>
    confidence?: number
  }) => client.post<any, any>('/backtest/risk/var', params),
  riskStressTest: (params: {
    stock_codes?: string[]
    portfolio_value?: number
    holdings?: Record<string, number>
  }) => client.post<any, any>('/backtest/risk/stress-test', params, { timeout: 60_000 }),
  riskCircuitBreaker: (params: {
    daily_pnl?: number
    weekly_pnl?: number
    monthly_pnl?: number
    consecutive_losses?: number
  }) => client.post<any, any>('/backtest/risk/circuit-breaker', null, { params }),

  // P2-A: Parameter Sensitivity Heatmap
  parameterHeatmap: (params: {
    preset?: string
    x_param?: string
    x_values?: number[]
    y_param?: string
    y_values?: number[]
    metric?: string
    stock_codes?: string[]
    sample_size?: number
    period_days?: number
  } = {}) =>
    client.post<any, HeatmapResult>('/backtest/parameter-heatmap', params, {
      timeout: 600_000,
    }),

  parameterHeatmapPresets: () =>
    client.get<any, Record<string, HeatmapPreset>>('/backtest/parameter-heatmap/presets'),
}

// P2-A: Heatmap Types
export interface HeatmapResult {
  x_param: string
  x_values: number[]
  x_label: string
  y_param: string
  y_values: number[]
  y_label: string
  metric: string
  matrix: (number | null)[][]
  zones: string[][]
  all_metrics: Record<string, (number | null)[][]>
  stocks_used: number
  compute_time_sec: number
  default_x: number
  default_y: number
}

export interface HeatmapPreset {
  x_param: string
  x_values: number[]
  x_label: string
  y_param: string
  y_values: number[]
  y_label: string
}
