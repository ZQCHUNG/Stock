import client from './client'

export interface AlertConfig {
  sqs_threshold: number
  notify_browser: boolean
  notify_line: boolean
  line_token: string
  notify_telegram: boolean    // R56
  telegram_bot_token: string  // R56
  telegram_chat_id: string    // R56
  watch_codes: string[]
  scheduler_interval: number
}

export interface SchedulerStatus {
  running: boolean
  next_run: string | null
  last_check: {
    timestamp: string | null
    triggered_count: number
    triggered: AlertTriggered[]
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

// --- Alert Check / History Types ---

export interface AlertTriggered {
  code: string
  name: string
  sqs: number
  grade: string
  timestamp: string
  [key: string]: unknown
}

export interface AlertCheckResult {
  triggered: AlertTriggered[]
  checked_count: number
  timestamp: string
}

export interface AlertHistoryItem {
  code: string
  name: string
  sqs: number
  grade: string
  triggered_at: string
  notified: boolean
  [key: string]: unknown
}

export interface AlertHealthResult {
  scheduler_running: boolean
  last_check: string | null
  config_valid: boolean
  [key: string]: unknown
}

export interface RuleCheckResult {
  rule_id: string
  rule_name: string
  triggered: boolean
  matches: Record<string, unknown>[]
  [key: string]: unknown
}

export const alertsApi = {
  getConfig: () => client.get<any, AlertConfig>('/alerts/config'),
  saveConfig: (config: AlertConfig) => client.post<any, { ok: boolean }>('/alerts/config', config),
  checkAlerts: () => client.get<any, AlertCheckResult>('/alerts/check'),
  triggerCheck: () => client.post<any, AlertCheckResult>('/alerts/trigger-check'),
  notifyTriggered: () => client.post<any, { sent: number }>('/alerts/notify-triggered'),
  getHistory: () => client.get<any, AlertHistoryItem[]>('/alerts/history'),
  getSchedulerStatus: () => client.get<any, SchedulerStatus>('/alerts/scheduler-status'),
  getHealth: () => client.get<any, AlertHealthResult>('/alerts/health'),

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
  deleteRule: (id: string) => client.delete<any, { ok: boolean }>(`/alerts/rules/${id}`),
  checkRules: (codes?: string[]) =>
    client.post<any, RuleCheckResult[]>('/alerts/rules/check', codes || null, { timeout: 60000 }),
  getConditionTypes: () => client.get<any, ConditionTypeOption[]>('/alerts/condition-types'),

  // R56: Test notification
  sendTest: (message?: string) =>
    client.post<any, { ok: boolean; message?: string }>('/alerts/send-test', { message: message || undefined }),
}
