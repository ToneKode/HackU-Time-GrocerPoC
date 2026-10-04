<script setup>
// Shopper dashboard. Every number comes from a backend:
//   persistance :8003 GET /accounts/{id}/dashboard  -> paid orders, spend by category, benefits
//   policy      :8001 GET /policy_stats/{id}        -> how often agent runs failed the policy check
import { computed, watch, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { session, syncProfile, accountRevision } from '../stores/auth.js'
import * as api from '../lib/api.js'
import GiftList from '../components/GiftList.vue'
import { money, giftLines, paidLines } from '../lib/format.js'
import { storeName } from '../i18n/index.js'

const { t, te, locale } = useI18n()
const data = ref(null)
const policy = ref(null)
const error = ref('')
const policyError = ref('')
const loading = ref(false)
const openOrder = ref('')
const hover = ref(-1)

const BENEFIT_KINDS = ['cash', 'asiamiles', 'membership_points', 'loyalty_points']
const COLORS = ['#2f7d5b', '#e0a43a', '#3f6fb5', '#c25b4e', '#7b5ea7', '#3a9aa3', '#b0794a', '#6d8a2f', '#9b9b9b']

async function load() {
  data.value = null
  policy.value = null
  loading.value = false
  if (!session.user?.id) return
  loading.value = true
  error.value = ''
  policyError.value = ''
  const id = session.user.id
  const revision = accountRevision
  const [dash, stats, profile] = await Promise.allSettled([api.getDashboard(id), api.getPolicyStats(id), api.getProfile(id)])
  if (session.user?.id !== id || revision !== accountRevision) return
  if (profile.status === 'fulfilled') syncProfile(profile.value, id)
  if (dash.status === 'fulfilled') data.value = dash.value
  else error.value = dash.reason?.message || 'error'
  if (stats.status === 'fulfilled') policy.value = stats.value
  else policyError.value = stats.reason?.message || 'error'
  loading.value = false
}
watch(() => session.user?.id, load, { immediate: true, flush: 'sync' })

function benefitLabel(kind) {
  const key = `agentCards.benefits.${kind}`
  return te(key) ? t(key) : kind
}
function benefitAmount(kind, value) {
  return kind === 'cash' ? money(value) : Number(value || 0).toLocaleString(locale.value, { maximumFractionDigits: 2 })
}
function ruleLabel(rule) {
  const key = `dashboard.rules.${rule}`
  return te(key) ? t(key) : rule
}
function when(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString(locale.value, { dateStyle: 'medium', timeStyle: 'short' })
}

// SVG pie: one path per category, angles from the share of goods spend.
const slices = computed(() => {
  const rows = data.value?.categories || []
  const total = rows.reduce((sum, row) => sum + row.amount, 0)
  if (!total) return []
  let angle = -Math.PI / 2
  return rows.map((row, index) => {
    const share = row.amount / total
    const start = angle
    const end = angle + share * Math.PI * 2
    angle = end
    const r = 80
    const x1 = 100 + r * Math.cos(start)
    const y1 = 100 + r * Math.sin(start)
    const x2 = 100 + r * Math.cos(end)
    const y2 = 100 + r * Math.sin(end)
    const large = end - start > Math.PI ? 1 : 0
    const path = share >= 0.9999
      ? 'M 100 20 A 80 80 0 1 1 99.99 20 Z'
      : `M 100 100 L ${x1.toFixed(2)} ${y1.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x2.toFixed(2)} ${y2.toFixed(2)} Z`
    return { ...row, share, path, color: COLORS[index % COLORS.length] }
  })
})
const totals = computed(() => data.value?.benefits?.totals || {})
const byMethod = computed(() => data.value?.benefits?.by_method || [])
const hasBenefits = computed(() => BENEFIT_KINDS.some((kind) => Number(totals.value[kind]) > 0))
</script>

<template>
  <main class="page dashboard-page">
    <header class="profile-head">
      <p class="sheet-kicker">{{ $t('dashboard.kicker') }}</p>
      <h1>{{ $t('dashboard.title') }}</h1>
      <p class="muted">{{ $t('dashboard.lead') }}</p>
    </header>

    <section v-if="!session.user" class="card">
      <p>{{ $t('dashboard.signIn') }}</p>
      <RouterLink to="/login" class="btn primary">{{ $t('menu.logIn') }}</RouterLink>
    </section>

    <template v-else>
      <section class="card">
        <h2>{{ $t('profile.limits.title') }}</h2>
        <dl class="rows">
          <dt>{{ $t('profile.limits.perOrder') }}</dt><dd>{{ money(session.user.per_order_cap) }}</dd>
          <dt>{{ $t('profile.limits.monthly') }}</dt><dd>{{ money(session.user.monthly_cap) }}</dd>
        </dl>
        <RouterLink to="/profile" class="link-btn">{{ $t('agentCards.editLimits') }}</RouterLink>
      </section>
      <p v-if="loading" class="muted">{{ $t('dashboard.loading') }}</p>
      <p v-if="error" class="sheet-alert" role="alert">{{ $t('dashboard.loadError', { message: error }) }}</p>

      <template v-if="data">
        <section class="profile-stats">
          <article>
            <span>{{ $t('dashboard.lifetime') }}</span>
            <strong>{{ money(data.lifetime_spent) }}</strong>
          </article>
          <article>
            <span>{{ $t('dashboard.ordersPaid') }}</span>
            <strong>{{ data.orders_paid }}</strong>
          </article>
          <article>
            <span>{{ $t('dashboard.average') }}</span>
            <strong>{{ money(data.average_order) }}</strong>
          </article>
        </section>

        <section class="card">
          <h2>{{ $t('dashboard.byCategory') }}</h2>
          <p class="muted small">{{ $t('dashboard.byCategoryHint', { goods: money(data.goods_total), fees: money(data.fees_and_offers) }) }}</p>
          <p v-if="!slices.length" class="muted">{{ $t('dashboard.noOrders') }}</p>
          <div v-else class="pie-wrap">
            <svg viewBox="0 0 200 200" class="pie" role="img" :aria-label="$t('dashboard.pieLabel')">
              <path
                v-for="(slice, index) in slices"
                :key="slice.category"
                :d="slice.path"
                :fill="slice.color"
                :class="{ 'pie-dim': hover >= 0 && hover !== index }"
                @mouseenter="hover = index"
                @mouseleave="hover = -1"
              >
                <title>{{ slice.category }}: {{ money(slice.amount) }} ({{ Math.round(slice.share * 100) }}%)</title>
              </path>
              <circle cx="100" cy="100" r="42" class="pie-hole" />
              <text x="100" y="97" text-anchor="middle" class="pie-total">{{ money(data.goods_total) }}</text>
              <text x="100" y="114" text-anchor="middle" class="pie-sub">{{ $t('dashboard.goods') }}</text>
            </svg>
            <ul class="pie-legend">
              <li v-for="(slice, index) in slices" :key="slice.category" @mouseenter="hover = index" @mouseleave="hover = -1">
                <i :style="{ background: slice.color }" />
                <span>{{ slice.category }}</span>
                <strong>{{ money(slice.amount) }}</strong>
                <em>{{ (slice.share * 100).toFixed(1) }}% · {{ $t('dashboard.items', { n: slice.items }) }}</em>
              </li>
            </ul>
          </div>
        </section>

        <section class="card">
          <h2>{{ $t('dashboard.benefits') }}</h2>
          <p class="muted small">{{ $t('dashboard.benefitsHint') }}</p>
          <div class="benefit-grid">
            <article v-for="kind in BENEFIT_KINDS" :key="kind">
              <span>{{ benefitLabel(kind) }}</span>
              <strong>{{ benefitAmount(kind, totals[kind]) }}</strong>
            </article>
          </div>
          <table v-if="hasBenefits && byMethod.length" class="dash-table">
            <thead>
              <tr>
                <th>{{ $t('dashboard.method') }}</th>
                <th v-for="kind in BENEFIT_KINDS" :key="kind">{{ benefitLabel(kind) }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in byMethod" :key="row.route">
                <td>{{ row.label }}<span v-if="row.last4" class="muted"> ···· {{ row.last4 }}</span></td>
                <td v-for="kind in BENEFIT_KINDS" :key="kind">{{ row.benefits[kind] ? benefitAmount(kind, row.benefits[kind]) : '–' }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="card">
          <h2>{{ $t('dashboard.history') }}</h2>
          <p v-if="!data.orders.length" class="muted">{{ $t('dashboard.noOrders') }}</p>
          <ul v-else class="order-history">
            <li v-for="order in data.orders" :key="order.id">
              <button type="button" class="order-row" :aria-expanded="openOrder === order.id" @click="openOrder = openOrder === order.id ? '' : order.id">
                <span class="order-when">{{ when(order.created_at) }}</span>
                <span class="order-what">
                  <strong>{{ order.merchant ? storeName(order.merchant) : $t('dashboard.order') }}</strong>
                  <span class="muted small">{{ $t('dashboard.items', { n: order.items }) }} · {{ order.tenders.map((t) => t.label).join(', ') }}</span>
                </span>
                <strong class="tile-price">{{ money(order.amount) }}</strong>
              </button>
              <div v-if="openOrder === order.id" class="order-detail">
                <p class="muted small">{{ order.intent }}</p>
                <p class="muted small">
                  {{ $t('dashboard.orderIds', { id: order.id, payment: order.payment_id || '–', rail: order.payment_order_id || '–' }) }}
                </p>
                <ul class="order-lines">
                  <li v-for="line in paidLines(order.lines)" :key="line.sku">
                    <span>{{ line.qty }} × {{ line.name }}</span>
                    <span class="muted small">{{ line.category }}</span>
                    <span>{{ money(line.line_total) }}</span>
                  </li>
                </ul>
                <GiftList :gifts="giftLines(order)" />
                <p v-if="order.benefits.length" class="small">
                  {{ $t('dashboard.earned') }}
                  <span v-for="benefit in order.benefits" :key="benefit.kind" class="pay-option">
                    {{ benefitLabel(benefit.kind) }} {{ benefitAmount(benefit.kind, benefit.amount) }}
                  </span>
                </p>
              </div>
            </li>
          </ul>
        </section>
      </template>

      <section class="card">
        <h2>{{ $t('dashboard.agent') }}</h2>
        <p v-if="policyError" class="muted">{{ $t('dashboard.policyError', { message: policyError }) }}</p>
        <template v-else-if="policy">
          <div class="benefit-grid">
            <article>
              <span>{{ $t('dashboard.runsChecked') }}</span>
              <strong>{{ policy.runs_checked }}</strong>
            </article>
            <article>
              <span>{{ $t('dashboard.runsFailed') }}</span>
              <strong>{{ policy.runs_failed }}</strong>
            </article>
            <article>
              <span>{{ $t('dashboard.runsHalted') }}</span>
              <strong>{{ policy.runs_halted }}</strong>
            </article>
            <article>
              <span>{{ $t('dashboard.runsEscalated') }}</span>
              <strong>{{ policy.runs_escalated }}</strong>
            </article>
          </div>
          <p class="muted small">{{ $t('dashboard.agentHint', { checks: policy.checks }) }}</p>
          <p v-if="!policy.by_rule.length" class="muted">{{ $t('dashboard.noFailures') }}</p>
          <table v-else class="dash-table">
            <thead>
              <tr>
                <th>{{ $t('dashboard.rule') }}</th>
                <th>{{ $t('dashboard.verdict') }}</th>
                <th>{{ $t('dashboard.times') }}</th>
                <th>{{ $t('dashboard.example') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in policy.by_rule" :key="row.rule">
                <td>{{ ruleLabel(row.rule) }}</td>
                <td>{{ row.status }}</td>
                <td>{{ row.count }}</td>
                <td class="small">
                  <span v-for="ex in row.examples.slice(0, 1)" :key="ex.ts + ex.run_id">
                    {{ when(ex.ts) }} · {{ money(ex.amount) }} · {{ ex.reason }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
          <template v-if="policy.recent_failures.length">
            <h3>{{ $t('dashboard.recent') }}</h3>
            <ul class="order-lines">
              <li v-for="ex in policy.recent_failures" :key="ex.ts + ex.run_id + ex.rule">
                <span>{{ when(ex.ts) }} · {{ $t(`dashboard.stages.${ex.stage || 'other'}`) }}</span>
                <span class="muted small">{{ ruleLabel(ex.rule) }} – {{ ex.reason }}</span>
                <span>{{ money(ex.amount) }}</span>
              </li>
            </ul>
          </template>
          <p v-if="policy.escalations.count" class="small">
            {{ $t('dashboard.escalations', { n: policy.escalations.count }) }}
            <span v-for="(n, status) in policy.escalations.by_status" :key="status" class="pay-option">{{ status }}: {{ n }}</span>
          </p>
        </template>
      </section>
    </template>
  </main>
</template>
