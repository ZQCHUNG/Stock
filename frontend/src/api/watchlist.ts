import client from './client'

// --- Watchlist Types ---

export interface WatchlistItem {
  code: string
  name: string
}

export interface WatchlistMutateResult {
  ok: boolean
  watchlist: string[]
}

export interface WatchlistOverviewItem {
  code: string
  name: string
  price?: number
  change_pct?: number
  volume_lots?: number
  signal?: string
  entry_type?: string
  signal_maturity?: string
  uptrend_days?: number
  rsi?: number | null
  adx?: number | null
  sector?: string
  industry?: string
  error?: boolean
}

export interface BatchBacktestItem {
  code: string
  name: string
  total_return?: number
  annual_return?: number
  max_drawdown?: number
  sharpe_ratio?: number
  win_rate?: number
  total_trades?: number
  profit_factor?: number
  error?: boolean
}

export interface RiskAuditStock {
  code: string
  name: string
  price?: number
  signal?: string
  entry_type?: string
  signal_maturity?: string
  rsi?: number | null
  adx?: number | null
  uptrend_days?: number
  sector?: string
  industry?: string
  is_biotech?: boolean
  visibility?: string
  inst_score?: number
  op_runway?: number
  total_runway?: number
  eff_runway?: number
  liquidity_factor?: number
  suggested_lots?: number
  stop_loss_price?: number
  max_loss?: number
  avg_volume_lots?: number
  warnings?: string[]
  error?: string
}

export interface RiskAuditSummary {
  total_stocks: number
  valid_stocks: number
  top_sector: string
  top_sector_pct: number
  biotech_count: number
  biotech_pct: number
  avg_liquidity_factor: number
  ghost_town_count: number
  buy_signal_count: number
  portfolio_warnings: string[]
  audit_time: string
  capital: number
  risk_pct: number
}

export interface RiskAuditResult {
  stocks: RiskAuditStock[]
  summary: RiskAuditSummary
}

export const watchlistApi = {
  get: () => client.get<any, WatchlistItem[]>('/watchlist/'),
  add: (code: string) => client.post<any, WatchlistMutateResult>(`/watchlist/${code}`),
  remove: (code: string) => client.delete<any, WatchlistMutateResult>(`/watchlist/${code}`),
  batchAdd: (codes: string[]) => client.post<any, WatchlistMutateResult>('/watchlist/batch-add', { codes }),
  overview: () => client.get<any, WatchlistOverviewItem[]>('/watchlist/overview'),
  batchBacktest: (req?: Record<string, unknown>) => client.post<any, BatchBacktestItem[]>('/watchlist/batch-backtest', req || {}),
  riskAudit: (capital?: number, riskPct?: number) =>
    client.get<any, RiskAuditResult>('/watchlist/risk-audit', { params: { capital, risk_pct: riskPct } }),
}
