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
  riskFactors: (code: string) => client.get<any, any>(`/analysis/${code}/risk-factors`),
  sectorHeat: () => client.get<any, any>('/analysis/sector-heat'),
  v5Signal: (code: string) => client.get<any, any>(`/analysis/${code}/v5-signal`),
  adaptiveSignal: (code: string) => client.get<any, any>(`/analysis/${code}/adaptive-signal`),
  riskBudget: (code: string) => client.get<any, any>(`/analysis/${code}/risk-budget`),
  strategyFitness: (codes?: string) => client.get<any, any>('/analysis/strategy-fitness', {
    params: codes ? { codes } : {},
  }),
  runFitnessScan: (periodDays = 730, maxWorkers = 4) =>
    client.post<any, any>('/analysis/strategy-fitness/scan', null, {
      params: { period_days: periodDays, max_workers: maxWorkers },
      timeout: 600_000,  // 10 min timeout for batch scan
    }),
}
