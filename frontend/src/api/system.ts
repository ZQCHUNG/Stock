import client from './client'

export const systemApi = {
  cacheStats: () => client.get<any, any>('/system/cache-stats'),
  flushCache: () => client.post<any, any>('/system/flush-cache'),
  recentStocks: () => client.get<any, any[]>('/system/recent-stocks'),
  addRecentStock: (code: string) => client.post<any, any>(`/system/recent-stocks/${code}`),
  workerHeartbeat: () => client.get<any, any>('/system/worker-heartbeat'),
  v4Params: () => client.get<any, any>('/system/v4-params'),
  transitionAlerts: (limit: number = 20) => client.get<any, any[]>(`/system/transition-alerts?limit=${limit}`),
  health: (includeSlow: boolean = false) => client.get<any, any>(`/system/health?include_slow=${includeSlow}`, { timeout: 30000 }),
  runBackup: () => client.post<any, any>('/system/backup'),
  listBackups: () => client.get<any, any[]>('/system/backups'),
  dataQuality: () => client.get<any, any>('/system/data-quality', { timeout: 60000 }),
  apiPerformance: () => client.get<any, any>('/system/api-performance'),
  omsEvents: (limit: number = 50) => client.get<any, any>(`/system/oms-events?limit=${limit}`),
  omsStats: () => client.get<any, any>('/system/oms-stats'),
  omsRunNow: () => client.post<any, any>('/system/oms-run', {}, { timeout: 60000 }),
  omsEfficiency: () => client.get<any, any>('/system/oms-efficiency'),
  performanceAttribution: () => client.get<any, any>('/system/performance-attribution'),
  dashboard: () => client.get<any, any>('/system/dashboard', { timeout: 30000 }),
  exceptionDashboard: () => client.get<any, any>('/system/exception-dashboard', { timeout: 30000 }),
  emergencyStop: () => client.post<any, any>('/system/emergency-stop', {}, { timeout: 10000 }),

  // P2-B: Auto-Sim Pipeline
  autoSim: (sendNotify = true) =>
    client.post<any, AutoSimResult>('/system/auto-sim', null, {
      params: { send_notify: sendNotify },
      timeout: 600_000,
    }),

  // P3: Signal Log + Drift Detection
  signalLog: (status: string = 'all', limit: number = 100) =>
    client.get<any, any[]>(`/system/signal-log?status=${status}&limit=${limit}`),
  realizeSignals: () =>
    client.post<any, any>('/system/signal-log/realize'),
  driftReport: () =>
    client.get<any, DriftReport>('/system/drift-report'),
  weeklyAudit: () =>
    client.post<any, any>('/system/weekly-audit', {}, { timeout: 120000 }),
  riskFlag: () =>
    client.get<any, RiskFlag>('/system/risk-flag'),
  setRiskFlag: (riskOn: boolean, reason: string = 'manual') =>
    client.post<any, RiskFlag>('/system/risk-flag', null, {
      params: { risk_on: riskOn, reason },
    }),

  // Phase 5: Pipeline Monitor
  pipelineMonitor: () =>
    client.get<any, PipelineMonitor>('/system/pipeline-monitor', { timeout: 15000 }),

  // Phase 6 P0: Trailing Stops
  updateTrailingStops: () =>
    client.post<any, TrailingStopResult>('/system/trailing-stops/update', {}, { timeout: 60000 }),

  // Phase 6 P1: Daily Summary (Ask My System)
  dailySummary: () => client.get<any, any>('/system/daily-summary', { timeout: 15000 }),

  // Phase 6 P2: Failure Analysis
  failureAnalysis: (daysBack: number = 90) =>
    client.get<any, FailureAnalysisResult>(`/system/failure-analysis?days_back=${daysBack}`, { timeout: 30000 }),

  // Phase 7 P2: Missed Opportunities
  missedOpportunities: (daysBack: number = 30, limit: number = 50) =>
    client.get<any, MissedOppsResult>(`/system/missed-opportunities?days_back=${daysBack}&limit=${limit}`),

  // Phase 8 P0: Self-Healed Events
  selfHealedEvents: () => client.get<any, SelfHealedEvents>('/system/self-healed-events'),

  // Phase 8 P1: Sector Heatmap
  sectorHeatmap: () => client.get<any, SectorHeatmapData>('/system/sector-heatmap'),

  // Phase 9 P1: War Room (Virtual Portfolio Equity Curve)
  warRoom: () => client.get<any, WarRoomData>('/system/war-room', { timeout: 30000 }),

  // Phase 10 P0: Stress Test
  stressTest: (stressDays: number = 3, slippage: number = 0.95) =>
    client.get<any, StressTestResult>(`/system/stress-test?stress_days=${stressDays}&slippage=${slippage}`, { timeout: 30000 }),

  // Phase 10 P1: Aggressive Index
  aggressiveIndex: () => client.get<any, AggressiveIndex>('/system/aggressive-index', { timeout: 15000 }),

  // Phase 11 P1: Live Trade Sync
  confirmLiveTrade: (signalId: number, actualPrice: number) =>
    client.post<any, any>(`/system/signal/${signalId}/confirm-live?actual_price=${actualPrice}`),

  // Phase 12 P0: Slippage Audit
  slippageAudit: () => client.get<any, SlippageAuditResult>('/system/slippage-audit', { timeout: 15000 }),

  // Phase 13 Task 2: Shake-out Audit
  shakeOutAudit: () => client.get<any, ShakeOutResult>('/system/shake-out-audit', { timeout: 60000 }),

  // Phase 14 Task 1: AI Signal Commentator
  aiComment: (stockCode: string) =>
    client.post<any, AiCommentResult>(`/system/ai-comment/${stockCode}`, {}, { timeout: 120000 }),

  // Phase 14 Task 3: Parameter Recommendations
  paramRecommendations: (daysBack: number = 90) =>
    client.get<any, ParamRecommendations>(`/system/param-recommendations?days_back=${daysBack}`, { timeout: 30000 }),

  // V1.1 P1: Energy Score Sparkline
  energyTrend: (stockCode: string, daysBack: number = 3) =>
    client.get<any, EnergyTrendPoint[]>(`/system/energy-trend/${stockCode}?days_back=${daysBack}`),

  // Phase 9 P0: Industry Success Rates
  industrySuccessRates: (daysBack: number = 90) =>
    client.get<any, any>(`/system/industry-success-rates?days_back=${daysBack}`),

  // R55-2: CSV export (returns Blob for download)
  exportBacktestCsv: (result: any) =>
    client.post('/system/export/backtest/csv', result, {
      responseType: 'blob' as any, timeout: 30000,
    }),
  exportPortfolioCsv: () =>
    client.get('/system/export/portfolio/csv', {
      responseType: 'blob' as any, timeout: 30000,
    }),
  exportScreenerCsv: (results: any[], filters?: any) =>
    client.post('/system/export/screener/csv', { results, filters }, {
      responseType: 'blob' as any, timeout: 30000,
    }),
  exportReportCsv: (report: any) =>
    client.post('/system/export/report/csv', report, {
      responseType: 'blob' as any, timeout: 30000,
    }),

  // R57: PDF export (returns Blob for download)
  exportReportPdf: (code: string) =>
    client.get(`/system/export/report/pdf/${code}`, {
      responseType: 'blob' as any, timeout: 120000,
    }),
  exportPortfolioPdf: () =>
    client.get('/system/export/portfolio/pdf', {
      responseType: 'blob' as any, timeout: 120000,
    }),
  exportBacktestPdf: (code: string, period: number = 1095) =>
    client.get(`/system/export/backtest/pdf/${code}?period=${period}`, {
      responseType: 'blob' as any, timeout: 120000,
    }),
}

// P2-B: Auto-Sim Types
export interface AutoSimSignal {
  stock_code: string
  name: string
  rs_rating: number
  industry: string
  tier: 'sniper' | 'tactical' | 'avoid'
  mean_similarity: number
  confidence_score: number
  confidence_grade: 'HIGH' | 'MEDIUM' | 'LOW'
  d21_win_rate: number | null
  d21_mean: number | null
  d21_expectancy: number | null
  ci_low: number | null
  ci_high: number | null
  worst_case_pct: number | null
  sample_count: number
  divergence_warning: boolean
  // Phase 7 P0: Energy Score
  energy_overheat?: boolean
  energy_weak_volume?: boolean
  energy_tr_ratio?: number | null
  energy_vol_ratio?: number | null
  energy_warnings?: string[]
  // Phase 9 P0: Success Rate Back-weighting
  success_rate_adj?: number
  industry_success_rate?: number | null
  industry_signal_count?: number
}

export interface AutoSimResult {
  candidates_found: number
  simulated: number
  top_signals: AutoSimSignal[]
  message: string
  elapsed_s: number
  notification_sent?: boolean
  ai_comments?: Record<string, string>
}

// Phase 14 Task 1: AI Signal Commentator
export interface AiCommentResult {
  stock_code: string
  comment: string
  signal_id?: number
}

// P3: Drift Detection Types
export interface RiskFlag {
  global_risk_on: boolean
  reason: string
  updated_at: string
}

export interface InBoundsResult {
  total_realized: number
  in_bounds_count: number
  in_bounds_rate: number | null
  above_ci: number
  below_ci: number
  healthy: boolean
}

export interface ZScoreResult {
  consecutive_breaches: number
  max_consecutive: number
  breach_signals: Array<{
    stock_code: string
    signal_date: string
    actual: number
    worst_case: number
  }>
  alarm: boolean
}

export interface DriftReport {
  in_bounds: InBoundsResult
  z_score: ZScoreResult
  risk_flag: RiskFlag
}

// Phase 5: Pipeline Monitor Types
export interface PipelineFileStatus {
  key: string
  description: string
  exists: boolean
  last_modified?: string
  age_hours?: number
  size_mb?: number
  stale: boolean
  status: 'fresh' | 'stale' | 'missing'
}

export interface PipelineMonitor {
  overall: 'healthy' | 'degraded' | 'critical'
  fresh_count: number
  total_count: number
  files: PipelineFileStatus[]
  scheduler: Record<string, any>
  checked_at: string
}

// Phase 6 P0: Trailing Stops
export interface ActiveStop {
  stock_code: string
  stock_name: string
  entry_price: number
  current_price: number
  current_stop: number
  trailing_phase: number
  phase_reason: string
  return_pct: number
  stop_distance_pct: number
  // Phase 7 P1: Scale-out
  target_1r_price?: number
  scale_out_triggered?: boolean
  scale_out_just_triggered?: boolean
}

export interface TrailingStopResult {
  updated: number
  errors: number
  active_stops: ActiveStop[]
}

// Phase 6 P2: Failure Analysis
export interface FailureAnalysis {
  stock_code: string
  signal_date: string
  category: 'EARNINGS' | 'SYSTEMIC' | 'NEWS' | 'TECHNICAL'
  summary: string
  physical_data: {
    entry_price: number
    exit_price: number
    atr_at_entry: number | null
    actual_pct: number
    worst_case_pct: number
    excess_loss_pct: number
  }
  evidence: string[]
  ai_opinion: string | null
}

export interface FailureAnalysisResult {
  failures: FailureAnalysis[]
  count: number
}

// Phase 7 P2: Missed Opportunities
export interface FilteredSignal {
  signal_date: string
  stock_code: string
  stock_name: string
  raw_score: number
  final_score: number
  filter_reason: string
  tr_ratio: number | null
  vol_ratio: number | null
  rs_rating: number
  tier: string
}

export interface MissedOppsResult {
  filtered: FilteredSignal[]
  count: number
}

// Phase 8 P0: Self-Healed Events
export interface SelfHealedEvents {
  total_healed: number
  total_flagged: number
  events: Array<{
    stock_code: string
    date: string
    original_change_pct: number
    action: 'healed' | 'flagged'
    healed_price?: number
  }>
  last_run?: string
}

// Phase 8 P1: Sector Heatmap
export interface SectorHeatmapData {
  sectors: Array<{
    name: string
    median_rs: number
    count: number
    diamond_count: number
    diamond_pct: number
  }>
  top3: string[]
  total_sectors: number
}

// Phase 9 P1: War Room Data
export interface WarRoomEquityPoint {
  date: string
  equity: number
  drawdown_pct: number
  stock_code?: string
  return_pct?: number
}

export interface WarRoomData {
  label: string
  initial_equity: number
  final_equity: number
  total_return_pct: number
  total_trades: number
  win_rate: number
  expectancy: number
  max_drawdown_pct: number
  mdd_warning: boolean
  equity_curve: WarRoomEquityPoint[]
  active_count: number
  realized_count: number
}

// Phase 10 P1: Aggressive Index
export interface AggressiveIndexBreakdown {
  score: number
  max: number
  label: string
}

export interface AggressiveIndex {
  score: number
  regime: 'aggressive' | 'normal' | 'defensive'
  advice: string
  color: string
  breakdown: Record<string, AggressiveIndexBreakdown>
  label: string
}

// Phase 10 P0: Stress Test
export interface StressTestPosition {
  stock_code: string
  stock_name: string
  entry_price: number
  position_pct: number
  position_value: number
  stressed_value: number
  loss: number
  loss_pct: number
}

export interface StressTestResult {
  scenario: string
  initial_equity: number
  current_equity: number
  stressed_equity: number
  stressed_mdd_pct: number
  total_loss_pct: number
  total_loss: number
  is_bust: boolean
  bust_threshold_pct: number
  positions_at_risk: number
  total_exposure: number
  exposure_pct: number
  per_position_details: StressTestPosition[]
  stress_days: number
  slippage_multiplier: number
  crash_factor: number
  exit_factor: number
  recovery_needed_pct: number
}

// Phase 12 P0: Slippage Audit
export interface SlippageIndustry {
  industry: string
  count: number
  median_bps: number
  p95_bps: number
  avg_bps: number
  status: 'LOW' | 'HIGH' | 'INSUFFICIENT_DATA'
}

export interface SlippageAuditResult {
  total_live_trades: number
  avg_slippage_bps: number
  friction_drag_pct: number | null
  industries: SlippageIndustry[]
  high_friction_industries: string[]
  virtual_expectancy: number | null
}

// Phase 13 Task 2: Shake-out Detector
export interface ShakeOutDetail {
  stock_code: string
  stock_name: string
  exit_date: string
  stop_price: number
  post_3d_high: number
  recovery_pct: number
  is_shake_out: boolean
}

export interface ShakeOutResult {
  total_stopped_out: number
  shake_out_count: number
  shake_out_rate: number | null
  rate_warning: boolean
  details: ShakeOutDetail[]
}

// Phase 14 Task 3: Parameter Recommendations
export interface ParamRecommendation {
  category: 'stop_loss' | 'position_sizing' | 'entry' | 'trailing'
  severity: 'info' | 'warning' | 'critical'
  title: string
  detail: string
  evidence: Record<string, any>
  suggestion: string
}

export interface ParamRecommendations {
  recommendations: ParamRecommendation[]
  summary: string
  trade_count: number
  win_rate: number | null
  in_bounds_rate: number | null
  analysis_period: string
  generated_at: string
}

// V1.1 P1: Energy Score Sparkline
export interface EnergyTrendPoint {
  date: string
  energy_tr_ratio: number | null
  energy_vol_ratio: number | null
  confidence_score: number
}

/** Trigger browser file download from Blob response */
export function downloadBlob(data: any, filename: string) {
  const blob = data instanceof Blob ? data : new Blob([data], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
