import client from './client'

// --- Risk Summary ---

export interface RiskSummary {
  has_data: boolean
  message?: string
  portfolio?: {
    total_value: number
    stock_count: number
    portfolio_beta: number | null
  }
  var?: {
    var_1d_pct: number
    var_1d_amount: number
    var_5d_pct: number
    var_5d_amount: number
    stocks_used: number
  }
  correlation?: {
    codes: string[]
    matrix: number[][]
  } | null
  high_corr_pairs?: { stock_a: string; stock_b: string; correlation: number }[]
  betas?: Record<string, number>
  concentration?: {
    by_position: { code: string; name: string; value: number; pct: number; beta: number | null }[]
    by_sector: {
      sectors: Record<string, number>
      concentrated: boolean
    }
  }
  alerts?: string[]
}

// --- Position Size ---

export interface PositionSizeResult {
  suggested_lots: number
  suggested_shares: number
  risk_budget: number
  var_contribution: number
  error?: string
  [key: string]: unknown
}

// --- Scenario ---

export interface ScenarioResult {
  scenarios: {
    name: string
    description: string
    portfolio_loss_pct: number
    portfolio_loss_amount: number
    [key: string]: unknown
  }[]
}

// --- VaR Validation ---

export interface VarValidationResult {
  breach_rate: number
  expected_rate: number
  calibrated: boolean
  recommendations: string[]
  [key: string]: unknown
}

// --- R-Multiples ---

export interface RMultiplePosition {
  code: string
  name: string
  r_multiple: number
  status: string
  [key: string]: unknown
}

export interface RMultiplesResult {
  positions: RMultiplePosition[]
  expectancy: {
    value: number
    win_rate: number
    avg_win_r: number
    avg_loss_r: number
    total_trades: number
    [key: string]: unknown
  }
}

// --- Portfolio Heat ---

export interface PortfolioHeatResult {
  raw_heat: number
  effective_heat: number
  heat_zone: string
  positions: Record<string, unknown>[]
  sector_breakdown: Record<string, unknown>
  [key: string]: unknown
}

// --- Sector Correlation ---

export interface SectorCorrelationResult {
  sectors: string[]
  correlation_matrix: Record<string, Record<string, number>>
  heatmap: number[][]
  zscore_alerts: Record<string, unknown>[]
  flash_alerts: Record<string, unknown>[]
  systemic_risk: {
    score: number
    level: string
    label: string
    tighten_stops: boolean
  }
  risk_buckets: {
    buckets: Record<string, unknown>[]
    sector_to_bucket: Record<string, number>
  }
}

export const riskApi = {
  getSummary: () => client.get<any, RiskSummary>('/risk/summary', { timeout: 60000 }),
  getPositionSize: (params: {
    code: string
    entry_price: number
    confidence?: number
    account_value?: number
    var_limit_pct?: number
  }) => client.post<any, PositionSizeResult>('/risk/position-size', params, { timeout: 30000 }),
  getScenario: (account_value?: number) =>
    client.post<any, ScenarioResult>('/risk/scenario', { account_value: account_value || 1000000 }, { timeout: 30000 }),
  validateVar: () =>
    client.post<any, VarValidationResult>('/risk/validate-var', {}, { timeout: 120000 }),
  // R86: R-Multiple + Portfolio Heat
  getRMultiples: () => client.get<any, RMultiplesResult>('/risk/r-multiples', { timeout: 30000 }),
  getPortfolioHeat: () => client.get<any, PortfolioHeatResult>('/risk/portfolio-heat', { timeout: 60000 }),
  // R87: Sector Correlation Monitor
  getSectorCorrelation: () => client.get<any, SectorCorrelationResult>('/risk/sector-correlation', { timeout: 120000 }),
}
