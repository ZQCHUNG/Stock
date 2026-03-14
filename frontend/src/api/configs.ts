import client from './client'

export interface SavedConfig {
  name: string
  config: Record<string, unknown>
  updatedAt: string
}

export const configsApi = {
  list(type: 'backtest' | 'screener'): Promise<SavedConfig[]> {
    return client.get<any, SavedConfig[]>(`/configs/${type}`)
  },
  save(type: 'backtest' | 'screener', name: string, config: Record<string, unknown>): Promise<{ ok: boolean }> {
    return client.post<any, { ok: boolean }>(`/configs/${type}`, { name, config })
  },
  rename(type: 'backtest' | 'screener', name: string, newName: string): Promise<{ ok: boolean }> {
    return client.patch<any, { ok: boolean }>(`/configs/${type}/${encodeURIComponent(name)}`, { new_name: newName })
  },
  batchDelete(type: 'backtest' | 'screener', names: string[]): Promise<{ ok: boolean; deleted: number }> {
    return client.post<any, { ok: boolean; deleted: number }>(`/configs/${type}/batch-delete`, { names })
  },
  remove(type: 'backtest' | 'screener', name: string): Promise<{ ok: boolean }> {
    return client.delete<any, { ok: boolean }>(`/configs/${type}/${encodeURIComponent(name)}`)
  },
}
