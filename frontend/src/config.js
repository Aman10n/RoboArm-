const configuredApiUrl = import.meta.env.VITE_API_URL?.replace(/\/$/, '')

export const API_BASE_URL = configuredApiUrl || ''

export function getWebSocketUrl() {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL

  const baseUrl = configuredApiUrl
    ? new URL(configuredApiUrl, window.location.origin)
    : new URL(window.location.origin)
  const protocol = baseUrl.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${baseUrl.host}/ws/telemetry`
}
