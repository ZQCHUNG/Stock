import client from './client'

export interface EquityCurveData {
  dates: string[]
  values: number[]
}

export interface SavedBtResult {
  name: string
  stockCode: string
  stockName: string
  config: Record<string, unknown>
  metrics: Record<string, unknown>
  savedAt: string
  equityCurve?: EquityCurveData
}

export const btResultsApi = {
  list(): Promise<SavedBtResult[]> {
    return client.get<any, SavedBtResult[]>('/backtest-results')
  },
  listWithEquity(): Promise<SavedBtResult[]> {
    return client.get<any, SavedBtResult[]>('/backtest-results', { params: { include_equity: true } })
  },
  save(data: {
    name: string; stockCode: string; stockName: string;
    config: Record<string, unknown>; metrics: Record<string, unknown>;
    equityCurve?: EquityCurveData;
  }): Promise<{ ok: boolean }> {
    return client.post<any, { ok: boolean }>('/backtest-results', data)
  },
  remove(index: number): Promise<{ ok: boolean }> {
    return client.delete<any, { ok: boolean }>(`/backtest-results/${index}`)
  },
}
