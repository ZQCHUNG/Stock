/** Encode a config object into a base64 URL parameter */
export function encodeConfig(config: Record<string, any>): string {
  // Remove null/undefined values to keep URL short
  const clean: Record<string, any> = {}
  for (const [k, v] of Object.entries(config)) {
    if (v != null && v !== '' && v !== false) clean[k] = v
  }
  return btoa(JSON.stringify(clean))
}

/** Decode a base64 URL parameter back to a config object */
export function decodeConfig(encoded: string): Record<string, any> | null {
  try {
    return JSON.parse(atob(encoded))
  } catch {
    return null
  }
}

/** Build a shareable URL with config */
export function buildShareUrl(path: string, configType: string, config: Record<string, any>): string {
  const encoded = encodeConfig(config)
  const base = window.location.origin
  return `${base}${path}?cfg=${configType}&v=${encoded}`
}

/** Parse config from current URL query params */
export function parseUrlConfig(): { type: string; config: Record<string, any> } | null {
  const params = new URLSearchParams(window.location.search)
  const cfgType = params.get('cfg')
  const value = params.get('v')
  if (!cfgType || !value) return null
  const config = decodeConfig(value)
  if (!config) return null
  return { type: cfgType, config }
}
