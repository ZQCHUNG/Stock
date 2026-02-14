import client from './client'

export interface StockItem {
  code: string
  name: string
  market: string
}

export interface TimeSeriesData {
  dates: string[]
  columns: Record<string, (number | null)[]>
}

export const stocksApi = {
  list: () => client.get<any, StockItem[]>('/stocks/list'),
  search: (q: string) => client.get<any, StockItem[]>('/stocks/search', { params: { q } }),
  data: (code: string, periodDays = 365) =>
    client.get<any, TimeSeriesData>(`/stocks/${code}/data`, { params: { period_days: periodDays } }),
  info: (code: string) => client.get<any, any>(`/stocks/${code}/info`),
  name: (code: string) => client.get<any, { code: string; name: string }>(`/stocks/${code}/name`),
  fundamentals: (code: string) => client.get<any, any>(`/stocks/${code}/fundamentals`),
  news: (code: string) => client.get<any, any[]>(`/stocks/${code}/news`),
  institutional: (code: string, days = 20) =>
    client.get<any, TimeSeriesData>(`/stocks/${code}/institutional`, { params: { days } }),
  dividends: (code: string) => client.get<any, any>(`/stocks/${code}/dividends`),
  taiex: (periodDays = 365) =>
    client.get<any, TimeSeriesData>('/stocks/taiex/data', { params: { period_days: periodDays } }),
}
