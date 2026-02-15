/**
 * WebSocket composable for real-time market data (R55-1)
 *
 * Connects to /ws/market, manages subscriptions, provides reactive price data.
 * Auto-reconnects on disconnect with exponential backoff.
 */

import { ref, reactive, onUnmounted, computed } from 'vue'

export interface QuoteData {
  code: string
  name: string
  last_price: number | null
  change: number | null
  change_pct: number | null
  open: number | null
  high: number | null
  low: number | null
  prev_close: number | null
  volume: number | null
  bid_prices: (number | null)[]
  bid_volumes: (number | null)[]
  ask_prices: (number | null)[]
  ask_volumes: (number | null)[]
  timestamp: number
}

export interface MarketFeedStatus {
  running: boolean
  is_market_hours: boolean
  connections: number
  subscribed_codes: number
  cached_quotes: number
  poll_interval: number
  consecutive_errors: number
  last_poll_time: number
}

const ws = ref<WebSocket | null>(null)
const isConnected = ref(false)
const feedStatus = ref<MarketFeedStatus | null>(null)
const quotes = reactive<Map<string, QuoteData>>(new Map())
const subscribedCodes = ref<Set<string>>(new Set())
const lastError = ref<string>('')

let reconnectTimer: ReturnType<typeof setTimeout> | null = null
let reconnectAttempts = 0
const MAX_RECONNECT_DELAY = 30_000

function getWsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws/market`
}

function connect() {
  if (ws.value?.readyState === WebSocket.OPEN) return

  try {
    ws.value = new WebSocket(getWsUrl())
  } catch (e) {
    lastError.value = String(e)
    scheduleReconnect()
    return
  }

  ws.value.onopen = () => {
    isConnected.value = true
    reconnectAttempts = 0
    lastError.value = ''

    // Re-subscribe to previously subscribed codes
    if (subscribedCodes.value.size > 0) {
      const codes = Array.from(subscribedCodes.value)
      ws.value?.send(JSON.stringify({ type: 'subscribe', codes }))
    }
  }

  ws.value.onclose = () => {
    isConnected.value = false
    scheduleReconnect()
  }

  ws.value.onerror = () => {
    lastError.value = 'WebSocket connection error'
  }

  ws.value.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data)
      handleMessage(msg)
    } catch {
      // ignore parse errors
    }
  }
}

function handleMessage(msg: { type: string; data?: any; message?: string }) {
  switch (msg.type) {
    case 'price_update':
      if (msg.data?.code) {
        quotes.set(msg.data.code, msg.data as QuoteData)
      }
      break

    case 'snapshot':
      if (msg.data) {
        for (const [code, data] of Object.entries(msg.data)) {
          quotes.set(code, data as QuoteData)
        }
      }
      break

    case 'status':
      feedStatus.value = msg.data as MarketFeedStatus
      break

    case 'pong':
      break

    case 'error':
      lastError.value = msg.message || 'Unknown error'
      break
  }
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), MAX_RECONNECT_DELAY)
  reconnectAttempts++
  reconnectTimer = setTimeout(connect, delay)
}

function disconnect() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  reconnectAttempts = 0
  if (ws.value) {
    ws.value.onclose = null // Prevent auto-reconnect
    ws.value.close()
    ws.value = null
  }
  isConnected.value = false
}

function subscribe(codes: string[]) {
  codes.forEach(c => subscribedCodes.value.add(c))
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ type: 'subscribe', codes }))
  }
}

function unsubscribe(codes: string[]) {
  codes.forEach(c => subscribedCodes.value.delete(c))
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ type: 'unsubscribe', codes }))
  }
}

function requestSnapshot(codes: string[]) {
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ type: 'snapshot', codes }))
  }
}

function requestStatus() {
  if (ws.value?.readyState === WebSocket.OPEN) {
    ws.value.send(JSON.stringify({ type: 'status' }))
  }
}

function getQuote(code: string): QuoteData | undefined {
  return quotes.get(code)
}

/**
 * Main composable — call in component setup().
 * Automatically connects on first use and manages lifecycle.
 */
export function useMarketData() {
  // Auto-connect on first use
  if (!ws.value && !reconnectTimer) {
    connect()
  }

  // Clean up subscriptions when component unmounts (but keep connection alive)
  const localCodes: string[] = []
  onUnmounted(() => {
    if (localCodes.length > 0) {
      unsubscribe(localCodes)
    }
  })

  function subscribeLocal(codes: string[]) {
    localCodes.push(...codes)
    subscribe(codes)
  }

  function unsubscribeLocal(codes: string[]) {
    codes.forEach(c => {
      const idx = localCodes.indexOf(c)
      if (idx !== -1) localCodes.splice(idx, 1)
    })
    unsubscribe(codes)
  }

  const quotesCount = computed(() => quotes.size)

  return {
    // State
    isConnected,
    feedStatus,
    quotes,
    quotesCount,
    lastError,
    subscribedCodes,

    // Actions
    connect,
    disconnect,
    subscribe: subscribeLocal,
    unsubscribe: unsubscribeLocal,
    requestSnapshot,
    requestStatus,
    getQuote,
  }
}
