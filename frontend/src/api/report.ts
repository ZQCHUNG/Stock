import client from './client'

export const reportApi = {
  generate: (code: string, periodDays = 730, marketRegime?: string) =>
    client.post<any, any>(`/report/${code}/generate`, {
      period_days: periodDays,
      market_regime: marketRegime,
    }),
}
