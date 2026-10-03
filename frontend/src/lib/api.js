// The only four calls the frontend makes (contract.json -> "calls").
import * as mock from './mock.js'

const env = import.meta.env
// Live agent and policy unless a local env file sets VITE_USE_MOCK=true.
export const useMock = env.VITE_USE_MOCK === 'true'
const AGENT_URL = env.VITE_AGENT_URL || 'http://localhost:8002'
const POLICY_URL = env.VITE_POLICY_URL || 'http://localhost:8001'
export const PERSISTANCE_URL = env.VITE_PERSISTANCE_URL || 'http://localhost:8003'

async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const error = new Error(`${method} ${url} failed (${res.status})`)
    error.status = res.status
    throw error
  }
  return res.json()
}

// start_or_resume -> ActionPlan. Never send escalation_status.
export function sendIntent({ intent, monthly_spent, escalation_id, account_id }) {
  const body = { intent, monthly_spent }
  if (escalation_id) body.escalation_id = escalation_id
  if (account_id) body.account_id = account_id
  if (useMock) return mock.sendIntent(body)
  return request('POST', `${AGENT_URL}/agent/intent`, body)
}

export function registerAccount(body) {
  return request('POST', `${PERSISTANCE_URL}/accounts/register`, body)
}

export function loginAccount(body) {
  return request('POST', `${PERSISTANCE_URL}/accounts/login`, body)
}

export function getProfile(accountId) {
  return request('GET', `${PERSISTANCE_URL}/accounts/${encodeURIComponent(accountId)}/profile`)
}

export function getChat(accountId) {
  return request('GET', `${PERSISTANCE_URL}/accounts/${encodeURIComponent(accountId)}/chat`)
}

export function clearChatHistory(accountId) {
  return request('DELETE', `${PERSISTANCE_URL}/accounts/${encodeURIComponent(accountId)}/chat`)
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

// Shopper approval before the payment rail is charged.
export function authorizePayment({ payment_id, step_up_confirmed, account_id }) {
  const body = { payment_id, step_up_confirmed: Boolean(step_up_confirmed) }
  if (account_id) body.account_id = account_id
  if (useMock) return mock.authorizePayment(body)
  return request('POST', `${AGENT_URL}/agent/payment/authorize`, body)
}

export function confirmBasket(body) {
  if (useMock) return mock.confirmBasket(body)
  return request('POST', `${AGENT_URL}/agent/basket/confirm`, body)
}

export function approveBasket(body) {
  if (useMock) return mock.approveBasket(body)
  return request('POST', `${AGENT_URL}/agent/basket/approve`, body)
}

export function savePreferences(accountId, body) {
  return request('PATCH', `${PERSISTANCE_URL}/accounts/${encodeURIComponent(accountId)}/preferences`, body)
}

export function settleOrder(accountId, body) {
  return request('POST', `${PERSISTANCE_URL}/accounts/${encodeURIComponent(accountId)}/orders/settle`, body)
}

// read_audit_log -> AuditEntry[]
export function getAuditLog() {
  if (useMock) return mock.getAuditLog()
  return request('GET', `${POLICY_URL}/audit_log`)
}
