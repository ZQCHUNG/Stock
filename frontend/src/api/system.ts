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
}
