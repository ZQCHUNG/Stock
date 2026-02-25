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
}

export interface AutoSimResult {
  candidates_found: number
  simulated: number
  top_signals: AutoSimSignal[]
  message: string
  elapsed_s: number
  notification_sent?: boolean
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
