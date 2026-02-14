import client from './client'

export interface AlertConfig {
  sqs_threshold: number
  notify_browser: boolean
  notify_line: boolean
  line_token: string
  watch_codes: string[]
  scheduler_interval: number
}

export interface SchedulerStatus {
  running: boolean
  next_run: string | null
  last_check: {
    timestamp: string | null
    triggered_count: number
    triggered: any[]
    error: string | null
  }
}

export const alertsApi = {
  getConfig: () => client.get<any, AlertConfig>('/alerts/config'),
  saveConfig: (config: AlertConfig) => client.post<any, any>('/alerts/config', config),
  checkAlerts: () => client.get<any, any>('/alerts/check'),
  triggerCheck: () => client.post<any, any>('/alerts/trigger-check'),
  notifyTriggered: () => client.post<any, any>('/alerts/notify-triggered'),
  getHistory: () => client.get<any, any>('/alerts/history'),
  getSchedulerStatus: () => client.get<any, SchedulerStatus>('/alerts/scheduler-status'),
  getHealth: () => client.get<any, any>('/alerts/health'),
}
