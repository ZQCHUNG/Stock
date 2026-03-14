import client from './client'

export interface StrategyParams {
  adx_threshold: number
  ma_short: number
  ma_long: number
  ma_trend_days: number
  take_profit_pct: number
  stop_loss_pct: number
  trailing_stop_pct: number
  min_hold_days: number
  min_volume: number
  confidence_weight: number
  // R52 P1: Fundamental filters (null = disabled)
  min_roe: number | null
  max_pe: number | null
  min_market_cap: number | null
}

export interface Strategy {
  id: string
  name: string
  description: string
  params: StrategyParams
  is_default: boolean
  created_at: string
  updated_at: string
}

// --- Backtest / Adaptive Types ---

export interface StrategyBacktestResult {
  total_return: number
  annual_return: number
  max_drawdown: number
  sharpe_ratio: number
  win_rate: number
  total_trades: number
  profit_factor: number
  trades?: Record<string, unknown>[]
  equity_curve?: { dates: string[]; values: number[] }
  [key: string]: unknown
}

export interface AdaptiveRecommendation {
  recommended_strategy: string
  regime: string
  weights: Record<string, number>
  [key: string]: unknown
}

export interface BatchAdaptiveResult {
  results: Record<string, StrategyBacktestResult>
  summary?: Record<string, unknown>
  [key: string]: unknown
}

export const strategiesApi = {
  list: () => client.get<any, { strategies: Strategy[] }>('/strategies/'),
  get: (id: string) => client.get<any, Strategy>(`/strategies/${id}`),
  create: (data: { name: string; description?: string; params?: Partial<StrategyParams> }) =>
    client.post<any, { ok: boolean; strategy: Strategy }>('/strategies/', data),
  update: (id: string, data: { name?: string; description?: string; params?: Partial<StrategyParams> }) =>
    client.put<any, { ok: boolean; strategy: Strategy }>(`/strategies/${id}`, data),
  clone: (id: string) => client.post<any, { ok: boolean; strategy: Strategy }>(`/strategies/${id}/clone`),
  delete: (id: string) => client.delete<any, { ok: boolean }>(`/strategies/${id}`),
  backtest: (id: string, code: string) =>
    client.post<any, StrategyBacktestResult>(`/strategies/${id}/backtest/${code}`, {}, { timeout: 60000 }),
  adaptiveRecommendation: () =>
    client.get<any, AdaptiveRecommendation>('/strategies/adaptive-recommendation'),
  adaptiveBacktest: (code: string, params?: { period_days?: number; rebalance_days?: number; regime_lookback?: number }) =>
    client.post<any, StrategyBacktestResult>(`/strategies/adaptive-backtest/${code}`, params || {}, { timeout: 120000 }),
  batchAdaptiveBacktest: (codes?: string[], periodDays?: number) =>
    client.post<any, BatchAdaptiveResult>('/strategies/adaptive-backtest-batch', {
      codes: codes || ['0050', '2330', '2317'],
      period_days: periodDays || 1095,
    }, { timeout: 300000 }),
}
