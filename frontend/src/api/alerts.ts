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

export interface CompoundCondition {
  type: string
  value: number
  params: Record<string, any>
}

export interface CompoundRule {
  id: string
  name: string
  codes: string[]
  conditions: CompoundCondition[]
  combine_mode: 'AND' | 'OR'
  enabled: boolean
  notify_line: boolean
  notify_browser: boolean
  cooldown_hours: number
  created_at: number
  last_triggered: number
  trigger_count: number
}

export interface ConditionTypeOption {
  value: string
  label: string
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

  // R55-3: Compound alert rules
  listRules: () => client.get<any, CompoundRule[]>('/alerts/rules'),
  createRule: (rule: {
    name: string
    codes: string[]
    conditions: CompoundCondition[]
    combine_mode: string
    notify_line?: boolean
    notify_browser?: boolean
    cooldown_hours?: number
  }) => client.post<any, CompoundRule>('/alerts/rules', rule),
  updateRule: (id: string, updates: Record<string, any>) =>
    client.patch<any, CompoundRule>(`/alerts/rules/${id}`, updates),
  deleteRule: (id: string) => client.delete<any, any>(`/alerts/rules/${id}`),
  checkRules: (codes?: string[]) =>
    client.post<any, any>('/alerts/rules/check', codes || null, { timeout: 60000 }),
  getConditionTypes: () => client.get<any, ConditionTypeOption[]>('/alerts/condition-types'),
}
