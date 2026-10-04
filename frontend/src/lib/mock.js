// Fake agent + policy API that runs in the browser, so the UI works before
// the real services exist. Products, reasons and thoughts come from the
// contract examples; the policy follows cross_team_config.json's check order.
import contract from '../../contract.json'
import { sha256Hex, hashInput, genesis_prev_hash } from './hash.js'

const { happy_path, halted_monthly, escalation_bulk } = contract.examples
const rule = (id) => contract.active_rules.find((r) => r.id === id)
const PER_TX_CAP = rule('per_transaction_cap').amount
const BULK_CEILING = rule('bulk_ceiling').amount
const MONTHLY_CAP = rule('monthly_cap').amount
const TTL_SECONDS = rule('escalation_ttl').seconds
const DECLINE_TOTAL = 666

const escalations = new Map()
let lastAuditLog = []

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const round2 = (n) => Math.round(n * 100) / 100
const isoNow = (plusSeconds = 0) =>
  new Date(Date.now() + plusSeconds * 1000).toISOString().slice(0, 19) + 'Z'
const thoughtOf = (example, event) =>
  example.response.audit_log.find((e) => e.event === event).thought

function checkPolicy(amount, monthlySpent) {
  const base = {
    amount,
    currency: 'HKD',
    monthly_spent: monthlySpent,
    per_transaction_cap: PER_TX_CAP,
    monthly_cap: MONTHLY_CAP,
    bulk_ceiling: BULK_CEILING,
  }
  if (monthlySpent + amount > MONTHLY_CAP) {
    return { ...base, status: 'HALT', reason: 'Over HK$2000 monthly cap', monthly_remaining: round2(MONTHLY_CAP - monthlySpent) }
  }
  const remaining = round2(MONTHLY_CAP - monthlySpent - amount)
  if (amount > BULK_CEILING) return { ...base, status: 'HALT', reason: 'Over HK$800 bulk ceiling', monthly_remaining: remaining }
  if (amount > PER_TX_CAP) return { ...base, status: 'ESCALATE', reason: 'Over HK$500 per-transaction cap', monthly_remaining: remaining }
  return { ...base, status: 'PASS', reason: 'Under HK$500 cap', monthly_remaining: remaining }
}

function pay(amount) {
  if (amount === DECLINE_TOTAL) {
    return { success: false, order_id: null, charged: null, currency: null, payment_route: null, ts: null, error: 'card_declined' }
  }
  const orderId = 'ORD-' + Math.random().toString(36).slice(2, 8).toUpperCase()
  return { success: true, order_id: orderId, charged: amount, currency: 'HKD', payment_route: 'mastercard', ts: isoNow(), error: null }
}

function paymentStep(payment) {
  return payment.success
    ? { event: 'PAYMENT', status: 'COMPLETED', reason: 'Payment success', thought: thoughtOf(happy_path, 'PAYMENT') }
    : { event: 'PAYMENT', status: 'FAILED', reason: payment.error, thought: 'The card was declined. Stop.' }
}

async function appendEntries(log, steps) {
  const out = [...log]
  for (const step of steps) {
    const entry = {
      index: out.length,
      ts: isoNow(),
      ...step,
      prev_hash: out.length ? out.at(-1).hash : genesis_prev_hash,
    }
    entry.hash = await sha256Hex(hashInput(entry))
    out.push(entry)
  }
  lastAuditLog = out
  return out
}

// Escalation status changes to EXPIRED once its 10 minutes are over.
function refresh(record) {
  const esc = record.escalation
  esc.remaining_seconds = Math.max(0, Math.ceil((record.expiresAtMs - Date.now()) / 1000))
  if (esc.status === 'PENDING' && esc.remaining_seconds === 0) esc.status = 'EXPIRED'
}

export async function sendIntent({ intent, monthly_spent = 0, escalation_id }) {
  await wait(700)
  if (escalation_id) return resume(escalation_id)

  const example = /bulk|大包|批量/i.test(intent) ? escalation_bulk : happy_path
  const { product, quote, goal } = structuredClone(example.response)
  const policy = checkPolicy(quote.total_landed_cost, Number(monthly_spent))
  const plan = { intent, status: 'READY', goal: { ...goal, intent }, product, quote, policy, escalation: null, payment: null, audit_log: [] }

  // INTENT_RECEIVED, PLAN, SEARCH, CART_PRICED are the same in every example.
  const steps = example.response.audit_log.slice(0, 4).map(({ event, status, reason, thought }) => ({ event, status, reason, thought }))
  steps.push({ event: 'POLICY_CHECK', status: policy.status, reason: policy.reason, thought: thoughtOf(happy_path, 'POLICY_CHECK') })

  let record = null
  if (policy.status === 'HALT') {
    plan.status = 'HALTED'
    steps.push({ event: 'HALTED', status: 'HALTED', reason: policy.reason, thought: thoughtOf(halted_monthly, 'HALTED') })
  } else if (policy.status === 'ESCALATE') {
    const escalation = {
      escalation_id: 'esc_' + Date.now().toString(36),
      status: 'PENDING',
      ttl_seconds: TTL_SECONDS,
      expires_at: isoNow(TTL_SECONDS),
      remaining_seconds: TTL_SECONDS,
      amount: policy.amount,
      currency: 'HKD',
      merchant: product.merchant,
      sku: product.id,
      reason: policy.reason,
    }
    record = { escalation, expiresAtMs: Date.now() + TTL_SECONDS * 1000, plan: null, payment: null }
    escalations.set(escalation.escalation_id, record)
    plan.status = 'ESCALATED'
    plan.escalation = structuredClone(escalation)
    steps.push({ event: 'ESCALATION_CREATED', status: 'PENDING', reason: policy.reason, thought: thoughtOf(escalation_bulk, 'ESCALATION_CREATED') })
  } else {
    plan.payment = pay(policy.amount)
    plan.status = plan.payment.success ? 'COMPLETED' : 'FAILED'
    steps.push(paymentStep(plan.payment))
  }

  plan.audit_log = await appendEntries([], steps)
  if (record) record.plan = structuredClone(plan)
  return plan
}

async function resume(escalationId) {
  const record = escalations.get(escalationId)
  if (!record) throw new Error(`Unknown escalation: ${escalationId}`)
  refresh(record)
  const plan = structuredClone(record.plan)
  plan.escalation = structuredClone(record.escalation)
  if (record.escalation.status !== 'APPROVED') {
    plan.status = 'ABORTED'
    return plan
  }
  // Idempotent: approving twice never charges twice.
  record.payment ??= pay(plan.policy.amount)
  plan.payment = structuredClone(record.payment)
  plan.status = plan.payment.success ? 'COMPLETED' : 'FAILED'
  plan.audit_log = await appendEntries(plan.audit_log, [
    { event: 'ESCALATION_APPROVED', status: 'APPROVED', reason: record.escalation.reason, thought: 'The parent approved in time. Continue to payment.' },
    paymentStep(plan.payment),
  ])
  return plan
}

export async function getEscalation(id) {
  await wait(80)
  const record = escalations.get(id)
  if (!record) throw new Error(`Unknown escalation: ${id}`)
  refresh(record)
  return structuredClone(record.escalation)
}

export async function decide(id, decision) {
  await wait(200)
  const record = escalations.get(id)
  if (!record) throw new Error(`Unknown escalation: ${id}`)
  refresh(record)
  if (record.escalation.status === 'PENDING') {
    record.escalation.status = decision === 'APPROVE' ? 'APPROVED' : 'REFUSED'
  }
  return structuredClone(record.escalation)
}

export async function authorizePayment({ payment_id }) {
  await wait(200)
  return {
    success: true,
    order_id: 'ORD-mock',
    charged: 59.9,
    currency: 'HKD',
    payment_route: 'mastercard',
    ts: new Date().toISOString(),
    error: null,
    payment_id,
  }
}

export async function confirmBasket({ lines = [] }) {
  await wait(120)
  const priced = lines.map((line) => ({
    sku: line.sku,
    name: line.sku,
    merchant: 'Watsons',
    qty: line.qty || 1,
    unit_price: 29.9,
    line_total: 29.9 * (line.qty || 1),
    image_url: '',
  }))
  const subtotal = priced.reduce((sum, line) => sum + line.line_total, 0)
  return {
    intent: 'mock',
    status: 'READY',
    payment: null,
    payment_draft: null,
    lines: priced,
    settlement: {
      currency: 'HKD',
      subtotal,
      discount: 0,
      shipping_fee: subtotal >= 400 ? 0 : 30,
      tax: 0,
      total: subtotal + (subtotal >= 400 ? 0 : 30),
      merchants: [
        {
          merchant: 'Watsons',
          subtotal,
          payable: subtotal,
          payment: { route: 'mastercard', label: 'Mox Mastercard', bank: 'Mox', last4: '4242', amount: subtotal },
          lines: priced,
          because: 'Mock tender',
        },
      ],
      benefits: [{ kind: 'cash', amount: 1, detail: 'Mock cashback' }],
    },
    question: '',
    reply: 'Rules checked again.',
    audit_log: [],
    react: [],
  }
}

export async function approveBasket({ amount }) {
  await wait(120)
  return { ...pay(amount), payment_id: 'pay-mock' }
}

export async function getAuditLog() {
  await wait(80)
  return structuredClone(lastAuditLog)
}

export async function getAlternatives(body) {
  return { sku: body?.sku || '', alternatives: [] }
}

// Mock mode only (VITE_USE_MOCK=true): empty dashboard, no invented numbers.
export async function getDashboard(accountId) {
  return {
    account_id: accountId, lifetime_spent: 0, orders_paid: 0, average_order: 0, goods_total: 0, fees_and_offers: 0,
    categories: [], orders: [], monthly: [], orders_by_status: {},
    benefits: { totals: { cash: 0, asiamiles: 0, membership_points: 0, loyalty_points: 0 }, by_method: [], entries: 0 },
  }
}

export async function getPolicyStats(accountId) {
  return {
    account_id: accountId, checks: 0, runs_checked: 0, runs_failed: 0, runs_halted: 0, runs_escalated: 0, runs_passed: 0,
    by_rule: [], recent_failures: [], escalations: { count: 0, by_status: {}, recent: [] },
  }
}

export function recoverPayment(body) {
  return authorizePayment(body)
}

export async function recoverOrders() {
  return { recovered: [], pending: [] }
}
