// Agent, policy and account API calls.
import * as mock from './mock.js'

const env = import.meta.env
// Live agent and policy unless a local env file sets VITE_USE_MOCK=true.
export const useMock = env.VITE_USE_MOCK === 'true'
const AGENT_URL = env.VITE_AGENT_URL || '/api/agent'
const POLICY_URL = env.VITE_POLICY_URL || '/api/policy'
export const PERSISTANCE_URL = env.VITE_PERSISTANCE_URL || '/api/persistence'

async function request(method, url, body, headers = {}) {
  const res = await fetch(url, {
    method,
    headers: { ...(body ? { 'Content-Type': 'application/json' } : {}), ...headers },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const payload = await res.json().catch(() => null)
    const detail = typeof payload?.detail === 'string' ? payload.detail : ''
    const error = new Error(detail || `${method} ${url} failed (${res.status})`)
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

export function updateLimits(accountId, { per_order_cap, monthly_cap }) {
  return request('PATCH', `${PERSISTANCE_URL}/accounts/${encodeURIComponent(accountId)}/limits`, {
    per_order_cap,
    monthly_cap,
  })
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

export function recoverPayment({ payment_id, account_id }) {
  if (useMock) return mock.recoverPayment({ payment_id, account_id })
  return request('POST', `${AGENT_URL}/agent/payment/recover`, { payment_id, account_id })
}

export function recoverOrders(accountId) {
  if (useMock) return mock.recoverOrders(accountId)
  return request('POST', `${AGENT_URL}/agent/orders/recover?account_id=${encodeURIComponent(accountId)}`)
}

export function confirmBasket(body) {
  if (useMock) return mock.confirmBasket(body)
  return request('POST', `${AGENT_URL}/agent/basket/confirm`, body)
}

// Dashboard: paid orders, spend by category, benefits (persistance :8003).
export function getDashboard(accountId) {
  if (useMock) return mock.getDashboard(accountId)
  return request('GET', `${PERSISTANCE_URL}/accounts/${encodeURIComponent(accountId)}/dashboard`)
}

// Dashboard: policy check failures per rule for this shopper (policy :8001).
export function getPolicyStats(accountId) {
  if (useMock) return mock.getPolicyStats(accountId)
  return request('GET', `${POLICY_URL}/policy_stats/${encodeURIComponent(accountId)}`)
}

// Swap options for one basket line (same food group, real catalog rows).
export function getAlternatives(body) {
  if (useMock) return mock.getAlternatives(body)
  return request('POST', `${AGENT_URL}/agent/basket/alternatives`, body)
}

export function approveBasket(body) {
  if (useMock) return mock.approveBasket(body)
  return request('POST', `${AGENT_URL}/agent/basket/approve`, body)
}

// POST /accounts/{id}/payment-methods (persistance PaymentMethodIn).
// Only route, label and the last 4 digits travel. Never a full card number or CVV.
export function addPaymentMethod(accountId, { route, label, last4 = '', connected = true, is_default = false }) {
  return request('POST', `${PERSISTANCE_URL}/accounts/${encodeURIComponent(accountId)}/payment-methods`, {
    route,
    label,
    last4,
    connected: Boolean(connected),
    is_default: Boolean(is_default),
  })
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

export function marketRulesToPromotions(body) {
  return {
    version: body.version,
    payment_promotions: (body.payment_promotions || []).map((row) => ({ ...row, merchant: row.merchant ?? '' })),
    promotions: [
      ...(body.merchant_discounts || []).map((row, index) => ({ id: `discount-${index}`, merchant: row.merchant, kind: 'percent', threshold: row.threshold, rate: row.percent / 100, sku: '', enabled: true })),
      ...(body.sku_gifts || []).map((row, index) => ({ id: `gift-${index}`, merchant: '', kind: 'bogo', threshold: 0, rate: 0, sku: row.sku, gift_sku: row.gift_sku, enabled: true })),
    ],
  }
}

export function promotionsToMarketRules(promotions, paymentPromotions = []) {
  const enabled = promotions.filter((row) => row.enabled)
  return {
    payment_promotions: paymentPromotions.map(({ route, kind, rate, merchant = '', enabled }) => ({ route, kind, rate, merchant, enabled })),
    merchant_discounts: enabled.filter((row) => row.kind === 'percent').map((row) => ({ merchant: row.merchant, percent: Math.round(row.rate * 10000) / 100, threshold: row.threshold })),
    sku_gifts: enabled.filter((row) => row.kind === 'bogo').map((row) => ({ sku: row.sku, gift_sku: row.gift_sku || row.sku })),
  }
}

export async function getMarketRules(accountId, password) {
  const path = accountId ? `/admin/market/rules?account_id=${encodeURIComponent(accountId)}` : '/market/rules'
  const headers = accountId ? { 'X-Admin-Password': password } : {}
  return marketRulesToPromotions(await request('GET', `${PERSISTANCE_URL}${path}`, undefined, headers))
}

export async function saveMarketRules(accountId, body, password) {
  const paymentPromotions = body.payment_promotions ?? (await getMarketRules(accountId, password)).payment_promotions
  const rules = promotionsToMarketRules(body.promotions, paymentPromotions)
  await request('PUT', `${PERSISTANCE_URL}/admin/market/rules`, { account_id: accountId, rules }, { 'X-Admin-Password': password })
  return getMarketRules(accountId, password)
}

export function updateCatalogProduct(accountId, sku, body, password) {
  return request('PATCH', `${PERSISTANCE_URL}/admin/catalog/${encodeURIComponent(sku)}`, { account_id: accountId, price: body.price }, { 'X-Admin-Password': password })
}
