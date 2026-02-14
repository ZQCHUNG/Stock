import client from './client'

export interface SavedConfig {
  name: string
  config: Record<string, any>
  updatedAt: string
}

export const configsApi = {
  list(type: 'backtest' | 'screener'): Promise<SavedConfig[]> {
    return client.get(`/configs/${type}`) as any
  },
  save(type: 'backtest' | 'screener', name: string, config: Record<string, any>) {
    return client.post(`/configs/${type}`, { name, config }) as any
  },
  rename(type: 'backtest' | 'screener', name: string, newName: string) {
    return client.patch(`/configs/${type}/${encodeURIComponent(name)}`, { new_name: newName }) as any
  },
  batchDelete(type: 'backtest' | 'screener', names: string[]) {
    return client.post(`/configs/${type}/batch-delete`, { names }) as any
  },
  remove(type: 'backtest' | 'screener', name: string) {
    return client.delete(`/configs/${type}/${encodeURIComponent(name)}`) as any
  },
}
