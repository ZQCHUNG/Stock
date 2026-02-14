import client from './client'

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

export const portfolioApi = {
  list: () => client.get<any, any>('/portfolio/'),
  open: (params: OpenPositionParams) => client.post<any, any>('/portfolio/open', params),
  close: (id: string, params: ClosePositionParams) =>
    client.post<any, any>(`/portfolio/${id}/close`, params),
  update: (id: string, params: { stop_loss?: number; trailing_stop?: number; note?: string }) =>
    client.put<any, any>(`/portfolio/${id}`, params),
  delete: (id: string) => client.delete<any, any>(`/portfolio/${id}`),
  health: () => client.get<any, any>('/portfolio/health'),
  exitAlerts: () => client.get<any, any[]>('/portfolio/exit-alerts'),
  equityLedger: () => client.get<any, any>('/portfolio/equity-ledger'),
  analytics: () => client.get<any, any>('/portfolio/analytics'),
  performance: () => client.get<any, any>('/portfolio/performance'),
  briefing: () => client.get<any, any>('/portfolio/briefing'),
  stressTest: () => client.get<any, any>('/portfolio/stress-test'),
}
