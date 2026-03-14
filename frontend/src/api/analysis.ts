import client from './client'
import type { TimeSeriesData } from './stocks'

// --- V4 Signal ---

export interface V4Signal {
  signal: 'BUY' | 'HOLD' | 'SELL'
  entry_type?: string
  signal_maturity?: string
  uptrend_days?: number
  dist_ma20?: number
  confidence_score?: number
  stop_loss_price?: number
  indicators: Record<string, number | null>
  [key: string]: unknown
}

// --- V4 Enhanced ---

export interface V4EnhancedSignal extends V4Signal {
  institutional_gatekeeper?: Record<string, unknown>
  confidence_multiplier?: number
}

// --- Support / Resistance ---

export interface PriceLevel {
  price: number
  source: string
  strength: number
}

export interface SupportResistanceResult {
  current_price: number
  supports: PriceLevel[]
  resistances: PriceLevel[]
}

// --- Volume Patterns ---

export interface VolumePatternResult {
  patterns: Record<string, unknown>[]
  summary?: string
  [key: string]: unknown
}

// --- Market Regime ---

export interface MarketRegime {
  regime: 'bull' | 'bear' | 'sideways' | 'unknown'
  taiex_close?: number
  ma20?: number | null
  ma60?: number | null
  rsi?: number | null
}

export interface MarketRegimeMl {
  regime: string
  confidence?: number
  features?: Record<string, number>
  strategy_advice?: string
  error?: string
  [key: string]: unknown
}

// --- Risk Factors ---

export interface RiskFactorsResult {
  is_biotech: boolean
  cash_runway: Record<string, unknown> | null
  institutional: Record<string, unknown>
  avg_volume_20d: number
  liquidity_factor: number
  warnings: string[]
  current_price: number
  stop_loss_price: number | null
  v4_signal: string
  signal_maturity: string
  sector_l1: string
  sector_momentum: string
  is_leader: boolean
  confidence_multiplier: number
  confidence_breakdown: string[]
  industry: string
  sector: string
  atr_14: number | null
  highest_close_20d: number | null
  trailing_stop_price: number | null
}

// --- Sector Heat ---

export interface SectorHeatStock {
  code: string
  name: string
  maturity: string
}

export interface SectorHeatItem {
  sector: string
  total: number
  buy_count: number
  heat: number
  weighted_heat: number
  buy_stocks: SectorHeatStock[]
  all_stocks: string[]
  momentum?: string
  leader?: { code: string; name: string; leader_score: number } | null
}

export interface SectorHeatResult {
  sectors: SectorHeatItem[]
  scanned: number
  total_buy: number
  _updated_at?: string
}

// --- V5 Signal ---

export interface V5Signal {
  signal: 'BUY' | 'HOLD' | 'SELL'
  bias_confirmed?: boolean
  [key: string]: unknown
}

// --- Adaptive Signal ---

export interface AdaptiveSignalResult {
  v4: V4Signal
  v5: V5Signal
  adaptive: Record<string, unknown>
}

// --- Bold Signal ---

export interface BoldSignal {
  signal: 'BUY' | 'HOLD' | 'SELL'
  entry_type?: string
  confidence?: number
  [key: string]: unknown
}

// --- Liquidity ---

export interface LiquidityResult {
  score: number
  dtl_days: number
  spread_pct: number
  adv_ratio: number
  grade: string
  stress: boolean
  [key: string]: unknown
}

// --- Risk Budget ---

export interface RiskBudgetResult {
  code: string
  conflict: boolean
  v4_signal: string
  v5_signal: string
  exposure_limit: number
  kelly_half: number
  [key: string]: unknown
}

// --- Strategy Fitness ---

export interface FitnessTag {
  code: string
  tag: string
  [key: string]: unknown
}

export interface StrategyFitnessResult {
  stocks: FitnessTag[]
  summary: Record<string, unknown>
}

// --- Signal Tracker ---

export interface SignalTrackerRecordResult {
  recorded: number
  [key: string]: unknown
}

export interface SignalPerformanceResult {
  signals: Record<string, unknown>[]
  summary?: Record<string, unknown>
  [key: string]: unknown
}

export interface SignalAccuracyResult {
  strategies: Record<string, unknown>[]
  [key: string]: unknown
}

export interface SignalDecayResult {
  decay: Record<string, unknown>[]
  [key: string]: unknown
}

export interface SignalStockSummary {
  code: string
  strategies: Record<string, unknown>[]
  recent_signals: Record<string, unknown>[]
  [key: string]: unknown
}

// --- SQS ---

export interface SqsResult {
  sqs: number
  grade: string
  grade_label: string
  dimensions: Record<string, number>
  radar?: Record<string, number>
  [key: string]: unknown
}

export interface SqsDistributionResult {
  count: number
  scores: SqsResult[]
  percentiles?: Record<string, number>
  error?: string
  [key: string]: unknown
}

// --- Trail Classifier ---

export interface TrailClassifierResult {
  code: string
  mode: 'momentum_scalper' | 'precision_trender'
  atr_pct: number
  threshold_pct: number
  trail_description: string
  atr_14: number | null
  close: number
  history: number[]
}

// --- Sizing Advisor ---

export interface SizingAdvisorResult {
  code: string
  mode: string
  atr_pct: number
  entry_price: number
  capital: number
  sector: string
  odd_lot: boolean
  suggested_lots: number
  suggested_shares: number
  position_pct: number
  cost: number
  cost_pct: number
  regime_multiplier: number
  risk_per_trade_pct: number
  max_risk_pct: number
  base_lots: number
  base_cost: number
  sector_multiplier: number
  sector_penalty_applied: boolean
  sector_reason: string
  light: 'green' | 'yellow' | 'red'
  light_label: string
  over_risk: boolean
}

// --- Bold Status ---

export interface BoldStatusResult {
  code: string
  rs_rating: number | null
  rs_grade: string
  mls?: Record<string, unknown>
  ecf?: Record<string, unknown>
  bold_signal?: BoldSignal
  [key: string]: unknown
}

// --- RS Rankings ---

export interface RsRankingItem {
  code: string
  name: string
  rs_rating: number
  rs_ratio: number
  grade: string
  [key: string]: unknown
}

export interface RsRankingsResult {
  rankings: RsRankingItem[]
  scan_date?: string
  total?: number
}

// --- Sector Context (R64) ---

export interface SectorContextResult {
  code: string
  sector: string
  sector_rs: number
  peer_alpha: number
  beta_trap: boolean
  cluster_risk: string
  blind_spot: boolean
  [key: string]: unknown
}

// --- VCP (R85) ---

export interface VcpResult {
  code: string
  vcp_score: number
  vcp_breakout: boolean
  contractions: number
  t1_ratio: number
  ghost_day: boolean
  [key: string]: unknown
}

// --- Stop Levels (R86) ---

export interface StopLevelsResult {
  code: string
  entry_price: number
  initial_stop: number
  method_used: string
  atr_stop: number
  trailing_phases: Record<string, unknown>[]
  [key: string]: unknown
}

// --- Winner DNA Match (R90) ---

export interface WinnerDnaMatchResult {
  code: string
  status: string
  match_score?: number
  traffic_light?: 'green' | 'yellow' | 'red'
  best_cluster?: Record<string, unknown>
  knn_neighbors?: Record<string, unknown>[]
  divergence_warning?: boolean
  feature_attribution?: Record<string, number>
  [key: string]: unknown
}

// --- Pattern Library (R90) ---

export interface PatternLibraryResult {
  status: string
  build_date?: string
  version?: string
  n_samples?: number
  n_clusters?: number
  clusters?: Record<string, unknown>[]
  detail?: string
}

// --- Fitness Scan ---

export interface FitnessScanResult {
  scanned: number
  updated: number
  errors: number
  [key: string]: unknown
}

export const analysisApi = {
  indicators: (code: string, periodDays = 365, tail = 120) =>
    client.get<any, TimeSeriesData>(`/analysis/${code}/indicators`, {
      params: { period_days: periodDays, tail },
    }),
  v4Signal: (code: string) => client.get<any, V4Signal>(`/analysis/${code}/v4-signal`),
  v4Enhanced: (code: string) => client.get<any, V4EnhancedSignal>(`/analysis/${code}/v4-enhanced`),
  v4SignalsFull: (code: string, tail = 120) =>
    client.get<any, TimeSeriesData>(`/analysis/${code}/v4-signals-full`, { params: { tail } }),
  supportResistance: (code: string) => client.get<any, SupportResistanceResult>(`/analysis/${code}/support-resistance`),
  volumePatterns: (code: string) => client.get<any, VolumePatternResult>(`/analysis/${code}/volume-patterns`),
  marketRegime: () => client.get<any, MarketRegime>('/analysis/market-regime'),
  marketRegimeMl: () => client.get<any, MarketRegimeMl>('/analysis/market-regime-ml'),
  riskFactors: (code: string) => client.get<any, RiskFactorsResult>(`/analysis/${code}/risk-factors`),
  sectorHeat: () => client.get<any, SectorHeatResult>('/analysis/sector-heat'),
  v5Signal: (code: string) => client.get<any, V5Signal>(`/analysis/${code}/v5-signal`),
  adaptiveSignal: (code: string) => client.get<any, AdaptiveSignalResult>(`/analysis/${code}/adaptive-signal`),
  boldSignal: (code: string) => client.get<any, BoldSignal>(`/analysis/${code}/bold-signal`),
  liquidity: (code: string, positionNtd = 1_000_000) =>
    client.get<any, LiquidityResult>(`/analysis/${code}/liquidity`, { params: { position_ntd: positionNtd } }),
  riskBudget: (code: string) => client.get<any, RiskBudgetResult>(`/analysis/${code}/risk-budget`),
  strategyFitness: (codes?: string) => client.get<any, StrategyFitnessResult>('/analysis/strategy-fitness', {
    params: codes ? { codes } : {},
  }),
  runFitnessScan: (periodDays = 730, maxWorkers = 4) =>
    client.post<any, FitnessScanResult>('/analysis/strategy-fitness/scan', null, {
      params: { period_days: periodDays, max_workers: maxWorkers },
      timeout: 600_000,
    }),
  // Signal Tracker (Forward Testing)
  recordSignals: () => client.post<any, SignalTrackerRecordResult>('/analysis/signal-tracker/record'),
  fillForwardReturns: (lookbackDays = 10) =>
    client.post<any, SignalTrackerRecordResult>('/analysis/signal-tracker/fill', null, {
      params: { lookback_days: lookbackDays },
    }),
  signalPerformance: (days = 30, strategy?: string, code?: string) =>
    client.get<any, SignalPerformanceResult>('/analysis/signal-tracker/performance', {
      params: { days, ...(strategy ? { strategy } : {}), ...(code ? { code } : {}) },
    }),
  signalAccuracy: (days = 60) =>
    client.get<any, SignalAccuracyResult>('/analysis/signal-tracker/accuracy', { params: { days } }),
  signalDecay: (days = 90) =>
    client.get<any, SignalDecayResult>('/analysis/signal-tracker/decay', { params: { days } }),
  signalStockSummary: (code: string, days = 180) =>
    client.get<any, SignalStockSummary>(`/analysis/signal-tracker/${code}/summary`, { params: { days } }),
  sqs: (code: string) => client.get<any, SqsResult>(`/analysis/${code}/sqs`),
  batchSqs: (stocks: { code: string; strategy: string; maturity: string }[]) =>
    client.post<any, Record<string, SqsResult>>('/analysis/batch-sqs', { stocks }),
  sqsDistribution: () => client.get<any, SqsDistributionResult>('/analysis/sqs-distribution'),
  trailClassifier: (code: string) => client.get<any, TrailClassifierResult>(`/analysis/${code}/trail-classifier`),
  sizingAdvisor: (code: string, capital = 1_000_000, riskPct = 3.0, oddLot = false) =>
    client.get<any, SizingAdvisorResult>(`/analysis/${code}/sizing-advisor`, {
      params: { capital, risk_pct: riskPct, odd_lot: oddLot },
    }),
  // R63: RS Scanner & Bold Status
  boldStatus: (code: string) => client.get<any, BoldStatusResult>(`/analysis/${code}/bold-status`),
  rsRankings: () => client.get<any, RsRankingsResult>('/analysis/rs-rankings'),
  triggerRsScan: (maxWorkers = 8) =>
    client.post<any, { status: string; scanned: number }>('/analysis/rs-scan', null, {
      params: { max_workers: maxWorkers },
      timeout: 600_000,
    }),
  // R64: Sector RS & Peer Alpha
  sectorContext: (code: string) => client.get<any, SectorContextResult>(`/analysis/${code}/sector-context`),
  // R85: VCP (Volatility Contraction Pattern)
  vcp: (code: string) => client.get<any, VcpResult>(`/analysis/${code}/vcp`),
  // R86: ATR-Based Stop-Loss Calculator
  stopLevels: (code: string, entryPrice: number, entryType = 'squeeze_breakout') =>
    client.get<any, StopLevelsResult>(`/analysis/${code}/stop-levels`, {
      params: { entry_price: entryPrice, entry_type: entryType },
    }),
  // R90: Winner DNA Pattern Recognition
  winnerDnaMatch: (code: string) => client.get<any, WinnerDnaMatchResult>(`/analysis/${code}/winner-dna-match`),
  patternLibrary: () => client.get<any, PatternLibraryResult>('/analysis/pattern-library'),
}
