import client from './client'

export const watchlistApi = {
  get: () => client.get<any, any[]>('/watchlist/'),
  add: (code: string) => client.post<any, any>(`/watchlist/${code}`),
  remove: (code: string) => client.delete<any, any>(`/watchlist/${code}`),
  batchAdd: (codes: string[]) => client.post<any, any>('/watchlist/batch-add', { codes }),
  overview: () => client.get<any, any[]>('/watchlist/overview'),
  batchBacktest: (req?: any) => client.post<any, any[]>('/watchlist/batch-backtest', req || {}),
}
