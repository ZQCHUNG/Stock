import client from './client'

// --- Request Types ---

export interface OpenPositionParams {
  code: string
  name?: string
  entry_price: number
  lots: number
  stop_loss: number
  trailing_stop?: number | null
  confidence?: number
  sector?: string
  note?: string
  tags?: string
}

export interface ClosePositionParams {
  exit_price: number
  exit_reason?: string
}

// --- Position Types ---

export interface Position {
  id: string
  code: string
  name: string
  entry_price: number
  lots: number
  stop_loss: number
  trailing_stop?: number | null
  confidence: number
  sector: string
  note: string
  tags: string
  opened_at: string
  current_price?: number
  unrealized_pnl?: number
  unrealized_pct?: number
  stop_price?: number
  [key: string]: unknown
}

export interface ClosedPosition extends Position {
  exit_price: number
  exit_reason: string
  closed_at: string
  realized_pnl: number
  realized_pct: number
}

export interface PortfolioSummary {
  total_value: number
  total_cost: number
  total_pnl: number
  total_pnl_pct: number
  open_count: number
  [key: string]: unknown
}

export interface PortfolioListResult {
  positions: Position[]
  closed: ClosedPosition[]
  summary: PortfolioSummary
}

// --- Health ---

export interface PortfolioHealthResult {
  health_score: number
  checks: Record<string, unknown>[]
  warnings: string[]
  [key: string]: unknown
}

// --- Exit Alerts ---

export interface ExitAlert {
  code: string
  name: string
  reason: string
  urgency: string
  [key: string]: unknown
}

// --- Equity Ledger ---

export interface EquityLedgerResult {
  entries: Record<string, unknown>[]
  [key: string]: unknown
}

// --- Analytics ---

export interface PortfolioAnalytics {
  win_rate?: number
  avg_return?: number
  expectancy?: number
  [key: string]: unknown
}

// --- Performance ---

export interface PortfolioPerformance {
  total_return_pct: number
  sharpe_ratio?: number
  max_drawdown?: number
  [key: string]: unknown
}

// --- Briefing ---

export interface PortfolioBriefing {
  summary: string
  action_items: string[]
  [key: string]: unknown
}

// --- Stress Test ---

export interface PortfolioStressTest {
  scenarios: Record<string, unknown>[]
  [key: string]: unknown
}

// --- Correlation ---

export interface PortfolioCorrelation {
  matrix: number[][]
  codes: string[]
  high_pairs: Record<string, unknown>[]
  [key: string]: unknown
}

// --- Optimal Exposure ---

export interface OptimalExposure {
  has_data: boolean
  kelly_half?: number
  optimal_exposure?: number
  [key: string]: unknown
}

// --- Rebalance ---

export interface RebalanceResult {
  actions: Record<string, unknown>[]
  [key: string]: unknown
}

// --- Market Regime ---

export interface PortfolioMarketRegime {
  has_data: boolean
  regime?: string
  regime_en?: string
  [key: string]: unknown
}

// --- Efficient Frontier ---

export interface EfficientFrontierResult {
  frontier: Record<string, unknown>[]
  current_portfolio?: Record<string, unknown>
  [key: string]: unknown
}

// --- Behavioral Audit ---

export interface BehavioralAuditResult {
  biases: Record<string, unknown>[]
  score: number
  [key: string]: unknown
}

// --- Import CSV ---

export interface ImportCsvResult {
  imported: number
  errors: string[]
  [key: string]: unknown
}

// --- Rebalance Plan ---

export interface RebalancePlanResult {
  plan: Record<string, unknown>[]
  [key: string]: unknown
}

export const portfolioApi = {
  list: () => client.get<any, PortfolioListResult>('/portfolio/'),
  open: (params: OpenPositionParams) => client.post<any, { ok: boolean; position: Position }>('/portfolio/open', params),
  close: (id: string, params: ClosePositionParams) =>
    client.post<any, { ok: boolean }>(`/portfolio/${id}/close`, params),
  update: (id: string, params: { stop_loss?: number; trailing_stop?: number; note?: string }) =>
    client.put<any, { ok: boolean }>(`/portfolio/${id}`, params),
  delete: (id: string) => client.delete<any, { ok: boolean }>(`/portfolio/${id}`),
  health: () => client.get<any, PortfolioHealthResult>('/portfolio/health'),
  exitAlerts: () => client.get<any, ExitAlert[]>('/portfolio/exit-alerts'),
  equityLedger: () => client.get<any, EquityLedgerResult>('/portfolio/equity-ledger'),
  analytics: () => client.get<any, PortfolioAnalytics>('/portfolio/analytics'),
  performance: () => client.get<any, PortfolioPerformance>('/portfolio/performance'),
  briefing: () => client.get<any, PortfolioBriefing>('/portfolio/briefing'),
  stressTest: () => client.get<any, PortfolioStressTest>('/portfolio/stress-test'),
  correlation: () => client.get<any, PortfolioCorrelation>('/portfolio/correlation'),
  optimalExposure: () => client.get<any, OptimalExposure>('/portfolio/optimal-exposure'),
  simulateRebalance: (codes: string[]) =>
    client.post<any, RebalanceResult>('/portfolio/simulate-rebalance', { codes }),
  marketRegime: () => client.get<any, PortfolioMarketRegime>('/portfolio/market-regime'),
  efficientFrontier: () => client.get<any, EfficientFrontierResult>('/portfolio/efficient-frontier'),
  behavioralAudit: () => client.get<any, BehavioralAuditResult>('/portfolio/behavioral-audit'),
  importCsv: (csvText: string) =>
    client.post<any, ImportCsvResult>('/portfolio/import-csv', { csv_text: csvText }),
  rebalancePlan: () => client.post<any, RebalancePlanResult>('/portfolio/rebalance-plan'),
}
