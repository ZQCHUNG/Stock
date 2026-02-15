import client from './client'

export interface BacktestParams {
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
  strategyComparison: (code: string, req: StrategyComparisonParams = {}) =>
    client.post<any, any>(`/backtest/${code}/strategy-comparison`, req),
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
}
