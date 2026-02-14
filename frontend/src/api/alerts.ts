import client from './client'

export interface AlertConfig {
  sqs_threshold: number
  notify_browser: boolean
  notify_line: boolean
  line_token: string
  watch_codes: string[]
}

export const alertsApi = {
  getConfig: () => client.get<any, AlertConfig>('/alerts/config'),
  saveConfig: (config: AlertConfig) => client.post<any, any>('/alerts/config', config),
  checkAlerts: () => client.get<any, any>('/alerts/check'),
  notifyTriggered: () => client.post<any, any>('/alerts/notify-triggered'),
  getHistory: () => client.get<any, any>('/alerts/history'),
}
