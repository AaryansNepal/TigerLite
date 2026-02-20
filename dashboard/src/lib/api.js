/**
 * API client — all backend communication goes through here.
 *
 * Proxied via Vite dev server (dev) or nginx (prod) so no CORS issues.
 * Every function returns parsed JSON or throws on non-2xx status.
 */

const API_BASE = import.meta.env.VITE_API_URL || ''

async function fetchJSON(path) {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new Error(`API error: ${res.status}`)
  return res.json()
}

export async function getCustomerHealth() {
  return fetchJSON('/api/customer-health')
}

export async function getFindings() {
  return fetchJSON('/api/findings')
}

export async function getSessions() {
  return fetchJSON('/api/sessions')
}

export async function getSessionSnapshots(sessionId) {
  return fetchJSON(`/api/snapshots/${sessionId}`)
}

export async function getSnapshot(sessionId, version) {
  return fetchJSON(`/api/snapshots/${sessionId}/${version}`)
}

export async function getScenarioStatus() {
  return fetchJSON('/api/scenario/status')
}

export async function triggerAgent() {
  const res = await fetch(`${API_BASE}/api/agent/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  return res.json()
}

export async function triggerBadDeploy() {
  const res = await fetch(`${API_BASE}/api/scenario/trigger-bad-deploy`, { method: 'POST' })
  return res.json()
}

export function getSSEUrl() {
  return `${API_BASE}/api/agent/stream`
}
