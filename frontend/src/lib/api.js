// The only four calls the frontend makes (contract.json -> "calls").
import * as mock from './mock.js'

const env = import.meta.env
// Live agent and policy unless a local env file sets VITE_USE_MOCK=true.
export const useMock = env.VITE_USE_MOCK === 'true'
const AGENT_URL = env.VITE_AGENT_URL || 'http://localhost:8002'
const POLICY_URL = env.VITE_POLICY_URL || 'http://localhost:8001'

async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${method} ${url} failed (${res.status})`)
  return res.json()
}

// start_or_resume -> ActionPlan. Never send escalation_status.
export function sendIntent({ intent, monthly_spent, escalation_id }) {
  const body = { intent, monthly_spent }
  if (escalation_id) body.escalation_id = escalation_id
  if (useMock) return mock.sendIntent(body)
  return request('POST', `${AGENT_URL}/agent/intent`, body)
}

// read_escalation -> Escalation
export function getEscalation(id) {
  if (useMock) return mock.getEscalation(id)
  return request('GET', `${POLICY_URL}/escalations/${encodeURIComponent(id)}`)
}

// decide -> Escalation
export function decide(id, decision) {
  if (useMock) return mock.decide(id, decision)
  return request('POST', `${POLICY_URL}/escalations/${encodeURIComponent(id)}/decision`, { decision })
}

// read_audit_log -> AuditEntry[]
export function getAuditLog() {
  if (useMock) return mock.getAuditLog()
  return request('GET', `${POLICY_URL}/audit_log`)
}
