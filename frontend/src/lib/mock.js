// Fake agent + policy API that runs in the browser, so the UI works before
// the real services exist. Products, reasons and thoughts come from the
// contract examples; the policy follows cross_team_config.json's check order.
import contract from '../../contract.json'
import { products as catalogProducts } from '../data/catalog.js'
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

const previews = new Map() // preview_id -> priced plan waiting for Confirm

export async function sendIntent({ intent, monthly_spent = 0, escalation_id, preview, preview_id, items }) {
  await wait(700)
  if (escalation_id) return resume(escalation_id)
  if (preview_id) return confirmPreview(preview_id, Number(monthly_spent), items)

  const example = /bulk|大包|批量/i.test(intent) ? escalation_bulk : happy_path
  const { product, quote, goal } = structuredClone(example.response)
  const plan = { intent, status: 'READY', goal: { ...goal, intent }, product, quote, policy: null, escalation: null, payment: null, audit_log: [] }

  // INTENT_RECEIVED, PLAN, SEARCH, CART_PRICED are the same in every example.
  const priced = example.response.audit_log.slice(0, 4).map(({ event, status, reason, thought }) => ({ event, status, reason, thought }))
  plan.audit_log = await appendEntries([], priced)

  if (preview) {
    plan.preview_id = 'prv_' + Date.now().toString(36)
    previews.set(plan.preview_id, structuredClone(plan))
    return plan
  }
  return decideAndPay(plan, Number(monthly_spent))
}

async function confirmPreview(previewId, monthlySpent, items) {
  const saved = previews.get(previewId)
  previews.delete(previewId)
  if (!saved) {
    return { intent: '', status: 'FAILED', reply: 'This basket preview has expired. Please ask again.', audit_log: [], payment: null }
  }
  if (items) {
    const edited = reprice(items)
    if (!edited) {
      return { ...saved, status: 'FAILED', reply: 'Some items in the edited basket are no longer available. Please review it again.', payment: null }
    }
    Object.assign(saved, edited)
    saved.audit_log = await appendEntries(saved.audit_log, [{
      event: 'BASKET_REVISED',
      status: 'RECORDED',
      reason: `Shopper edited the basket before confirming. Landed HK$${edited.quote.total_landed_cost.toFixed(2)}.`,
      thought: 'The shopper changed the basket. The policy check sees the edited lines and total.',
    }])
  }
  return decideAndPay(saved, monthlySpent)
}

// ---- Products for the "add a product" picker ----
// The shop catalog at each product's cheapest store, plus the bulk item from the contract examples.
function mockProducts() {
  const list = catalogProducts.map((p) => {
    const best = [...p.offers].filter((o) => o.inStock !== false).sort((a, b) => a.price - b.price)[0]
    return best && {
      id: p.id, name: p.name, price: best.price, currency: 'HKD', merchant: best.merchant,
      category: p.category, stock: 50, image_url: '', sell_point: best.oldPrice ? 'cheap' : '',
    }
  }).filter(Boolean)
  list.push(structuredClone(escalation_bulk.response.product))
  return list
}

export async function listProducts() {
  await wait(250)
  return mockProducts()
}

// Same rules as the mall: HK$30 delivery under HK$400.
function reprice(items) {
  const byId = Object.fromEntries(mockProducts().map((p) => [p.id, p]))
  const wanted = items.filter((i) => i.qty > 0)
  if (!wanted.length || wanted.some((i) => !byId[i.sku])) return null
  const lines = wanted.map((i, index) => {
    const p = byId[i.sku]
    return {
      sku: p.id, name: p.name, merchant: p.merchant, category: p.category, sell_point: p.sell_point,
      qty: i.qty, unit_price: p.price, line_total: round2(p.price * i.qty),
      need: p.category, priority: index + 1, product_reason: 'Chosen in the basket review.', merchant_reason: '',
    }
  })
  const subtotal = round2(lines.reduce((sum, l) => sum + l.line_total, 0))
  const shipping = subtotal >= 400 ? 0 : 30
  const quote = {
    line_items: lines.map(({ sku, name, merchant, category, unit_price, qty, line_total }) => ({ sku, name, merchant, category, unit_price, qty, line_total })),
    subtotal, shipping_fee: shipping, tax: 0, total_landed_cost: round2(subtotal + shipping), currency: 'HKD', free_shipping_threshold: 400,
  }
  return { lines, quote, product: byId[lines[0].sku] }
}

// Policy check, then pay / escalate / halt. Continues the plan's audit chain.
async function decideAndPay(plan, monthlySpent) {
  const { product } = plan
  const policy = checkPolicy(plan.quote.total_landed_cost, monthlySpent)
  plan.policy = policy
  delete plan.preview_id
  const steps = []
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

  plan.audit_log = await appendEntries(plan.audit_log, steps)
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

export async function getAuditLog() {
  await wait(80)
  return structuredClone(lastAuditLog)
}
