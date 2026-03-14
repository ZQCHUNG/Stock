import client from './client'

// --- Request Types ---

export interface BacktestParams {
  period_days?: number
  initial_capital?: number
  params?: Record<string, unknown>
  commission_rate?: number
  tax_rate?: number
  slippage?: number
}

export interface BoldBacktestParams {
  period_days?: number
  initial_capital?: number
  params?: Record<string, unknown>
  ultra_wide?: boolean
  commission_rate?: number
  tax_rate?: number
  slippage?: number
  broker_discount?: number
  use_dynamic_slippage?: boolean
}

export interface AggressiveBacktestParams {
  period_days?: number
  initial_capital?: number
  params?: Record<string, unknown>
  commission_rate?: number
  tax_rate?: number
  slippage?: number
}

export interface StrategyComparisonParams {
  period_days?: number
  initial_capital?: number
  v4_params?: Record<string, unknown>
  v5_params?: Record<string, unknown>
}

// --- Backtest Result Types ---

export interface BacktestResult {
  total_return: number
  annual_return: number
  max_drawdown: number
  sharpe_ratio: number
  win_rate: number
  total_trades: number
  profit_factor: number
  calmar_ratio?: number
  trades?: BacktestTrade[]
  equity_curve?: { dates: string[]; values: number[] }
  [key: string]: unknown
}

export interface BacktestTrade {
  entry_date: string
  exit_date: string
  entry_price: number
  exit_price: number
  return_pct: number
  hold_days: number
  signal_type?: string
  [key: string]: unknown
}

// --- Portfolio Backtest ---

export interface PortfolioBacktestResult extends BacktestResult {
  per_stock: Record<string, BacktestResult>
  [key: string]: unknown
}

// --- Strategy Comparison ---

export interface StrategyComparisonResult {
  v4: BacktestResult
  v5: BacktestResult
  comparison: Record<string, unknown>
  [key: string]: unknown
}

// --- Rolling / Sensitivity ---

export interface RollingBacktestResult {
  windows: {
    start: string
    end: string
    metrics: BacktestResult
  }[]
  summary: Record<string, unknown>
  [key: string]: unknown
}

export interface SensitivityResult {
  param_results: Record<string, unknown>[]
  [key: string]: unknown
}

// --- Alpha Beta ---

export interface AlphaBetaResult {
  alpha: number
  beta: number
  r_squared: number
  [key: string]: unknown
}

// --- Meta Strategy ---

export interface MetaStrategyResult {
  best_strategy: string
  strategies: Record<string, BacktestResult>
  [key: string]: unknown
}

// --- SQS Backtest ---

export interface SqsBacktestResult {
  thresholds: Record<string, BacktestResult>
  [key: string]: unknown
}

// --- Rolling WFA ---

export interface RollingWfaResult {
  windows: Record<string, unknown>[]
  summary: Record<string, unknown>
  [key: string]: unknown
}

// --- Attribution Analysis ---

export interface AttributionResult {
  factors: Record<string, unknown>[]
  summary: Record<string, unknown>
  [key: string]: unknown
}

// --- Regime Barometer ---

export interface RegimeBarometerResult {
  regimes: Record<string, unknown>[]
  current_regime: string
  [key: string]: unknown
}

// --- Adaptive Sniper A/B ---

export interface AdaptiveSniperABResult {
  control: BacktestResult
  treatment: BacktestResult
  comparison: Record<string, unknown>
  [key: string]: unknown
}

// --- Forward Test ---

export interface ForwardTestSummary {
  total_signals: number
  open_positions: number
  closed_positions: number
  win_rate?: number | null
  avg_return?: number | null
  [key: string]: unknown
}

export interface ForwardTestSignal {
  id: number
  stock_code: string
  signal_date: string
  strategy: string
  entry_price?: number
  status: string
  [key: string]: unknown
}

export interface ForwardTestPosition {
  id: number
  signal_id: number
  stock_code: string
  entry_price: number
  current_price?: number
  return_pct?: number
  status: string
  [key: string]: unknown
}

export interface ForwardTestCompareResult {
  signals: Record<string, unknown>[]
  [key: string]: unknown
}

// --- Risk Assessment ---

export interface RiskAssessResult {
  risk_level: string
  alerts: string[]
  circuit_breaker: boolean
  [key: string]: unknown
}

export interface VarResult {
  var_pct: number
  var_amount: number
  confidence: number
  [key: string]: unknown
}

export interface RiskStressTestResult {
  scenarios: Record<string, unknown>[]
  [key: string]: unknown
}

export interface CircuitBreakerResult {
  triggered: boolean
  reasons: string[]
  [key: string]: unknown
}

// --- P2-A: Heatmap Types ---

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

// --- Simulation ---

export interface SimulationResult {
  paths: number[][]
  summary: Record<string, unknown>
  [key: string]: unknown
}

export const backtestApi = {
  v4: (code: string, req: BacktestParams = {}) =>
    client.post<any, BacktestResult>(`/backtest/${code}/v4`, req),
  v5: (code: string, req: BacktestParams = {}) =>
    client.post<any, BacktestResult>(`/backtest/${code}/v5`, req),
  adaptive: (code: string, req: BacktestParams = {}) =>
    client.post<any, BacktestResult>(`/backtest/${code}/adaptive`, req),
  portfolio: (stockCodes: string[], req: BacktestParams = {}) =>
    client.post<any, PortfolioBacktestResult>('/backtest/portfolio', { stock_codes: stockCodes, ...req }),
  simulation: (code: string, days = 30, req: BacktestParams = {}) =>
    client.post<any, SimulationResult>(`/backtest/${code}/simulation`, { days, ...req }),
  rolling: (code: string, windowMonths = 6, req: BacktestParams = {}) =>
    client.post<any, RollingBacktestResult>(`/backtest/${code}/rolling`, { window_months: windowMonths, ...req }),
  sensitivity: (code: string, req: BacktestParams = {}) =>
    client.post<any, SensitivityResult>(`/backtest/${code}/sensitivity`, req),
  alphaBeta: (code: string, req: BacktestParams = {}) =>
    client.post<any, AlphaBetaResult>(`/backtest/${code}/alpha-beta`, req),
  bold: (code: string, req: BoldBacktestParams = {}) =>
    client.post<any, BacktestResult>(`/backtest/${code}/bold`, req, { timeout: 120_000 }),
  aggressive: (code: string, req: AggressiveBacktestParams = {}) =>
    client.post<any, BacktestResult>(`/backtest/${code}/aggressive`, req, { timeout: 180_000 }),
  strategyComparison: (code: string, req: StrategyComparisonParams = {}) =>
    client.post<any, StrategyComparisonResult>(`/backtest/${code}/strategy-comparison`, req),
  portfolioBold: (periodDays = 1095, initialCapital = 10_000_000, params?: Record<string, unknown>, brokerDiscount = 1.0, useDynamicSlippage = false) =>
    client.post<any, PortfolioBacktestResult>('/backtest/portfolio-bold', {
      period_days: periodDays,
      initial_capital: initialCapital,
      params,
      broker_discount: brokerDiscount,
      use_dynamic_slippage: useDynamicSlippage,
    }, { timeout: 600_000 }),
  metaStrategy: (stockCodes: string[], periodDays = 730, initialCapital = 1_000_000) =>
    client.post<any, MetaStrategyResult>('/backtest/meta-strategy', {
      stock_codes: stockCodes,
      period_days: periodDays,
      initial_capital: initialCapital,
    }, { timeout: 300_000 }),
  sqsBacktest: (stockCodes?: string[], periodDays = 730, thresholds = [40, 60, 80]) =>
    client.post<any, SqsBacktestResult>('/backtest/sqs-backtest', {
      stock_codes: stockCodes || null,
      period_days: periodDays,
      thresholds,
      max_workers: 4,
    }, { timeout: 600_000 }),

  // Phase 10A: Rolling WFA
  rollingWfa: (windowMonths = 3, brokerDiscount = 0.28, useDynamicSlippage = true) =>
    client.post<any, RollingWfaResult>('/backtest/rolling-wfa', {
      window_months: windowMonths,
      broker_discount: brokerDiscount,
      use_dynamic_slippage: useDynamicSlippage,
    }, { timeout: 600_000 }),

  // Phase 10C: Attribution Analysis
  attributionAnalysis: (windowMonths = 3, brokerDiscount = 0.28, useDynamicSlippage = true) =>
    client.post<any, AttributionResult>('/backtest/attribution-analysis', {
      window_months: windowMonths,
      broker_discount: brokerDiscount,
      use_dynamic_slippage: useDynamicSlippage,
    }, { timeout: 600_000 }),

  // Phase 11: Regime Barometer
  regimeBarometer: (lookbackDays = 180, tradeWindow = 20) =>
    client.post<any, RegimeBarometerResult>('/backtest/regime-barometer', {
      lookback_days: lookbackDays,
      trade_window: tradeWindow,
    }, { timeout: 300_000 }),

  // Phase 12: Adaptive Sniper A/B Comparison
  adaptiveSniperAB: (periodDays = 1095, brokerDiscount = 0.28, useDynamicSlippage = true) =>
    client.post<any, AdaptiveSniperABResult>('/backtest/adaptive-sniper-ab', {
      period_days: periodDays,
      initial_capital: 10_000_000,
      broker_discount: brokerDiscount,
      use_dynamic_slippage: useDynamicSlippage,
    }, { timeout: 600_000 }),

  // R59: Forward Testing
  forwardTestSummary: () =>
    client.get<any, ForwardTestSummary>('/backtest/forward-test/summary'),
  forwardTestSignals: (limit = 50, status?: string) =>
    client.get<any, ForwardTestSignal[]>('/backtest/forward-test/signals', { params: { limit, status } }),
  forwardTestPositions: (limit = 50, status?: string) =>
    client.get<any, ForwardTestPosition[]>('/backtest/forward-test/positions', { params: { limit, status } }),
  forwardTestScan: (stockCodes?: string[]) =>
    client.post<any, { scanned: number; signals: number }>('/backtest/forward-test/scan', stockCodes, { timeout: 120_000 }),
  forwardTestOpen: (signalId: number, capital = 500_000) =>
    client.post<any, { ok: boolean; position: ForwardTestPosition }>(`/backtest/forward-test/open/${signalId}`, null, { params: { capital } }),
  forwardTestUpdate: () =>
    client.post<any, { updated: number }>('/backtest/forward-test/update'),
  forwardTestCompare: (stockCode?: string) =>
    client.get<any, ForwardTestCompareResult>('/backtest/forward-test/compare', { params: { stock_code: stockCode } }),

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
  }) => client.post<any, RiskAssessResult>('/backtest/risk/assess', params, { timeout: 60_000 }),
  riskVar: (params: {
    stock_codes?: string[]
    portfolio_value?: number
    holdings?: Record<string, number>
    confidence?: number
  }) => client.post<any, VarResult>('/backtest/risk/var', params),
  riskStressTest: (params: {
    stock_codes?: string[]
    portfolio_value?: number
    holdings?: Record<string, number>
  }) => client.post<any, RiskStressTestResult>('/backtest/risk/stress-test', params, { timeout: 60_000 }),
  riskCircuitBreaker: (params: {
    daily_pnl?: number
    weekly_pnl?: number
    monthly_pnl?: number
    consecutive_losses?: number
  }) => client.post<any, CircuitBreakerResult>('/backtest/risk/circuit-breaker', null, { params }),

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
