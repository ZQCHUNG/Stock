import client from './client'
import type { TimeSeriesData } from './stocks'

export const analysisApi = {
  indicators: (code: string, periodDays = 365, tail = 120) =>
    client.get<any, TimeSeriesData>(`/analysis/${code}/indicators`, {
      params: { period_days: periodDays, tail },
    }),
  v4Signal: (code: string) => client.get<any, any>(`/analysis/${code}/v4-signal`),
  v4Enhanced: (code: string) => client.get<any, any>(`/analysis/${code}/v4-enhanced`),
  v4SignalsFull: (code: string, tail = 120) =>
    client.get<any, TimeSeriesData>(`/analysis/${code}/v4-signals-full`, { params: { tail } }),
  supportResistance: (code: string) => client.get<any, any>(`/analysis/${code}/support-resistance`),
  volumePatterns: (code: string) => client.get<any, any>(`/analysis/${code}/volume-patterns`),
  marketRegime: () => client.get<any, any>('/analysis/market-regime'),
  marketRegimeMl: () => client.get<any, any>('/analysis/market-regime-ml'),
  riskFactors: (code: string) => client.get<any, any>(`/analysis/${code}/risk-factors`),
  sectorHeat: () => client.get<any, any>('/analysis/sector-heat'),
  v5Signal: (code: string) => client.get<any, any>(`/analysis/${code}/v5-signal`),
  adaptiveSignal: (code: string) => client.get<any, any>(`/analysis/${code}/adaptive-signal`),
  boldSignal: (code: string) => client.get<any, any>(`/analysis/${code}/bold-signal`),
  liquidity: (code: string, positionNtd = 1_000_000) =>
    client.get<any, any>(`/analysis/${code}/liquidity`, { params: { position_ntd: positionNtd } }),
  riskBudget: (code: string) => client.get<any, any>(`/analysis/${code}/risk-budget`),
  strategyFitness: (codes?: string) => client.get<any, any>('/analysis/strategy-fitness', {
    params: codes ? { codes } : {},
  }),
  runFitnessScan: (periodDays = 730, maxWorkers = 4) =>
    client.post<any, any>('/analysis/strategy-fitness/scan', null, {
      params: { period_days: periodDays, max_workers: maxWorkers },
      timeout: 600_000,  // 10 min timeout for batch scan
    }),
  // Signal Tracker (Forward Testing)
  recordSignals: () => client.post<any, any>('/analysis/signal-tracker/record'),
  fillForwardReturns: (lookbackDays = 10) =>
    client.post<any, any>('/analysis/signal-tracker/fill', null, {
      params: { lookback_days: lookbackDays },
    }),
  signalPerformance: (days = 30, strategy?: string, code?: string) =>
    client.get<any, any>('/analysis/signal-tracker/performance', {
      params: { days, ...(strategy ? { strategy } : {}), ...(code ? { code } : {}) },
    }),
  signalAccuracy: (days = 60) =>
    client.get<any, any>('/analysis/signal-tracker/accuracy', { params: { days } }),
  signalDecay: (days = 90) =>
    client.get<any, any>('/analysis/signal-tracker/decay', { params: { days } }),
  signalStockSummary: (code: string, days = 180) =>
    client.get<any, any>(`/analysis/signal-tracker/${code}/summary`, { params: { days } }),
  sqs: (code: string) => client.get<any, any>(`/analysis/${code}/sqs`),
  batchSqs: (stocks: { code: string; strategy: string; maturity: string }[]) =>
    client.post<any, any>('/analysis/batch-sqs', { stocks }),
  sqsDistribution: () => client.get<any, any>('/analysis/sqs-distribution'),
  trailClassifier: (code: string) => client.get<any, any>(`/analysis/${code}/trail-classifier`),
  sizingAdvisor: (code: string, capital = 1_000_000, riskPct = 3.0) =>
    client.get<any, any>(`/analysis/${code}/sizing-advisor`, {
      params: { capital, risk_pct: riskPct },
    }),
}
