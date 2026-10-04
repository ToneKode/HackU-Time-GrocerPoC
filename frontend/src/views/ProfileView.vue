<script setup>
import { computed, watch, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { session, syncProfile, accountRevision } from '../stores/auth.js'
import * as api from '../lib/api.js'
import { money } from '../lib/format.js'
import Icon from '../components/shop/Icon.vue'
import { ArrowDown01Icon, ArrowUp01Icon } from '@hugeicons/core-free-icons'

function current(id, revision) {
  return session.user?.id === id && accountRevision === revision
}

const { t, te } = useI18n()
const profile = ref(null)
const rank = ref([])
const methods = ref([])
const error = ref('')
const notice = ref('')
const busy = ref(false)
const limits = reactive({ per_order_cap: '', monthly_cap: '' })
const limitsBusy = ref(false)
const limitsError = ref('')
const limitsNotice = ref('')

function applyLimits(body, id) {
  syncProfile(body, id)
  limits.per_order_cap = String(body.per_order_cap ?? '')
  limits.monthly_cap = String(body.monthly_cap ?? '')
}

async function saveLimits() {
  const id = session.user?.id
  const revision = accountRevision
  if (!id || limitsBusy.value) return
  limitsNotice.value = ''
  limitsError.value = ''
  const valid = (value) => /^\d+(?:\.\d{1,2})?$/.test(String(value)) && Number.isFinite(Number(value)) && Number(value) > 0
  if (!valid(limits.per_order_cap) || !valid(limits.monthly_cap)) {
    limitsError.value = t('profile.limits.invalid')
    return
  }
  limitsBusy.value = true
  try {
    const body = await api.updateLimits(id, { per_order_cap: Number(limits.per_order_cap), monthly_cap: Number(limits.monthly_cap) })
    if (!current(id, revision)) return
    profile.value = body
    applyLimits(body, id)
    limitsNotice.value = t('profile.limits.saved')
  } catch (err) {
    if (current(id, revision)) limitsError.value = err.status === 422 ? t('profile.limits.invalid') : err.message
  } finally {
    if (current(id, revision)) limitsBusy.value = false
  }
}

// Routes the backends understand: persistance STARTER_METHODS (mastercard, alipay, visa),
// agent-brain benefits.INSTRUMENTS (same three) and payment rails (mastercard, unionpay).
// `card` routes need the last 4 digits; a wallet has none.
const ROUTES = [
  { route: 'mastercard', card: true, earns: ['cash', 'membership_points'] },
  { route: 'visa', card: true, earns: ['asiamiles'] },
  { route: 'unionpay', card: true, earns: [] },
  { route: 'alipay', card: false, earns: ['loyalty_points'] },
]
const BENEFIT_KINDS = ['cash', 'asiamiles', 'membership_points', 'loyalty_points']

const blankDraft = () => ({ route: 'mastercard', label: '', last4: '', connected: true, is_default: false })
const draft = reactive(blankDraft())
const adding = ref(false)
const addBusy = ref(false)
const addError = ref('')
const addNotice = ref('')

const draftRoute = computed(() => ROUTES.find((row) => row.route === draft.route) || ROUTES[0])
const topBenefit = computed({
  get: () => rank.value[0] || '',
  set: (kind) => {
    if (!kind || rank.value[0] === kind) return
    rank.value = [kind, ...rank.value.filter((item) => item !== kind)]
    notice.value = ''
  },
})

function routeLabel(route) {
  const key = `profile.routes.${route}`
  return te(key) ? t(key) : route
}

function earnedWith(kind) {
  return ROUTES.filter((row) => row.earns.includes(kind)).map((row) => routeLabel(row.route)).join(' · ')
}

// Digits only, at most four. A pasted full card number is dropped, never kept in state.
function onLast4Input(event) {
  const digits = String(event.target.value || '').replace(/\D/g, '')
  if (digits.length > 4) {
    draft.last4 = ''
    addError.value = t('profile.add.errFullNumber')
  } else {
    draft.last4 = digits
    addError.value = ''
  }
  event.target.value = draft.last4
}

function draftLabel() {
  return draft.label.trim() || routeLabel(draft.route)
}

function validateDraft() {
  if (!ROUTES.some((row) => row.route === draft.route)) return t('profile.add.errRoute')
  if (draftLabel().length > 80) return t('profile.add.errLabelLong')
  if (draftRoute.value.card && !/^\d{4}$/.test(draft.last4)) return t('profile.add.errLast4')
  const last4 = draftRoute.value.card ? draft.last4 : ''
  if (methods.value.some((row) => row.route === draft.route && (row.last4 || '') === last4)) {
    return t('profile.add.errDuplicate')
  }
  return ''
}

function openAdd() {
  Object.assign(draft, blankDraft())
  addError.value = ''
  addNotice.value = ''
  adding.value = true
}

async function addMethod() {
  const id = session.user?.id
  const revision = accountRevision
  if (!id || addBusy.value) return
  addNotice.value = ''
  addError.value = validateDraft()
  if (addError.value) return
  addBusy.value = true
  try {
    const body = await api.addPaymentMethod(id, {
      route: draft.route,
      label: draftLabel(),
      last4: draftRoute.value.card ? draft.last4 : '',
      connected: draft.connected,
      is_default: draft.is_default,
    })
    if (!current(id, revision)) return
    // Keep unsaved "connected" toggles on the cards that were already listed.
    const local = new Map(methods.value.map((row) => [row.id, row.connected]))
    profile.value = body
    methods.value = (body.payment_methods || []).map((row) => ({
      ...row,
      connected: local.has(row.id) ? local.get(row.id) : row.connected,
    }))
    Object.assign(draft, blankDraft())
    adding.value = false
    addNotice.value = t('profile.add.added')
  } catch (err) {
    if (!current(id, revision)) return
    addError.value = err.status === 422 ? t('profile.add.errRejected') : err.message
  } finally {
    if (current(id, revision)) addBusy.value = false
  }
}

function benefitLabel(kind) {
  const key = `agentCards.benefits.${kind}`
  return te(key) ? t(key) : kind
}

async function load() {
  const id = session.user?.id
  const revision = accountRevision
  profile.value = null
  busy.value = false
  limitsBusy.value = false
  addBusy.value = false
  rank.value = []
  methods.value = []
  limits.per_order_cap = ''
  limits.monthly_cap = ''
  error.value = ''
  notice.value = ''
  limitsError.value = ''
  limitsNotice.value = ''
  adding.value = false
  if (!id) return
  try {
    const body = await api.getProfile(id)
    if (!current(id, revision)) return
    applyLimits(body, id)
    profile.value = body
    rank.value = [...(body.benefit_rank || [])]
    methods.value = (body.payment_methods || []).map((row) => ({ ...row }))
  } catch (err) {
    if (!current(id, revision)) return
    error.value = err.message
  }
}

function move(index, direction) {
  const next = index + direction
  if (next < 0 || next >= rank.value.length) return
  const copy = rank.value.slice()
  const [item] = copy.splice(index, 1)
  copy.splice(next, 0, item)
  rank.value = copy
  notice.value = ''
}

async function save() {
  if (!session.user?.id || busy.value) return
  const id = session.user.id
  const revision = accountRevision
  busy.value = true
  notice.value = ''
  error.value = ''
  try {
    const body = await api.savePreferences(id, {
      benefit_rank: rank.value,
      methods: methods.value.map((row) => ({ id: row.id, connected: row.connected })),
    })
    if (!current(id, revision)) return
    profile.value = body
    rank.value = [...body.benefit_rank]
    methods.value = body.payment_methods.map((row) => ({ ...row }))
    notice.value = t('profile.saved')
  } catch (err) {
    if (!current(id, revision)) return
    error.value = err.message
  } finally {
    if (current(id, revision)) busy.value = false
  }
}

watch(() => session.user?.id, load, { immediate: true, flush: 'sync' })
</script>

<template>
  <main class="page profile-page">
    <header class="profile-head">
      <p class="sheet-kicker">{{ $t('profile.kicker') }}</p>
      <h1>{{ $t('profile.title') }}</h1>
      <p class="muted">{{ $t('profile.lead') }}</p>
    </header>

    <section v-if="!session.user" class="card">
      <p>{{ $t('profile.signIn') }}</p>
      <RouterLink to="/login" class="btn primary">{{ $t('menu.logIn') }}</RouterLink>
    </section>

    <template v-else-if="profile">
      <section class="profile-stats">
        <article>
          <span>{{ $t('profile.remaining') }}</span>
          <strong>{{ money(profile.monthly_remaining) }}</strong>
        </article>
        <article>
          <span>{{ $t('agentCards.spent') }}</span>
          <strong>{{ money(profile.monthly_spent) }}</strong>
        </article>
        <article>
          <span>{{ $t('agentCards.cap') }}</span>
          <strong>{{ money(profile.monthly_cap) }}</strong>
        </article>
      </section>

      <form class="card" novalidate @submit.prevent="saveLimits">
        <h2>{{ $t('profile.limits.title') }}</h2>
        <p id="limits-hint" class="muted small">{{ $t('profile.limits.hint') }}</p>
        <div class="method-form-grid">
          <label class="field">
            <span>{{ $t('profile.limits.perOrder') }}</span>
            <input v-model="limits.per_order_cap" type="number" min="0.01" step="0.01" required aria-describedby="limits-hint limits-feedback" :aria-invalid="Boolean(limitsError)" :disabled="limitsBusy" />
          </label>
          <label class="field">
            <span>{{ $t('profile.limits.monthly') }}</span>
            <input v-model="limits.monthly_cap" type="number" min="0.01" step="0.01" required aria-describedby="limits-hint limits-feedback" :aria-invalid="Boolean(limitsError)" :disabled="limitsBusy" />
          </label>
        </div>
        <p id="limits-feedback" class="profile-note" :class="{ bad: limitsError }" aria-live="polite">{{ limitsError || limitsNotice }}</p>
        <button type="submit" class="btn primary" :disabled="limitsBusy">{{ $t(limitsBusy ? 'profile.limits.saving' : 'profile.limits.save') }}</button>
      </form>

      <section class="card">
        <h2>{{ $t('profile.methods') }}</h2>
        <p class="muted small">{{ $t('profile.methodsHint') }}</p>
        <ul class="method-list">
          <li v-for="method in methods" :key="method.id">
            <div>
              <strong>{{ method.label }}</strong>
              <span v-if="method.is_default" class="method-badge">{{ $t('profile.default') }}</span>
              <p class="muted small">
                {{ routeLabel(method.route) }}
                <template v-if="method.last4"> · {{ method.last4 }}</template>
              </p>
            </div>
            <label class="method-toggle">
              <input v-model="method.connected" type="checkbox" @change="notice = ''" />
              <span>{{ $t('profile.connected') }}</span>
            </label>
          </li>
        </ul>

        <p v-if="addNotice" class="profile-note">{{ addNotice }}</p>
        <button v-if="!adding" type="button" class="btn small method-add-open" @click="openAdd">
          + {{ $t('profile.add.open') }}
        </button>

        <form v-else class="method-form" novalidate @submit.prevent="addMethod">
          <h3>{{ $t('profile.add.title') }}</h3>
          <div class="method-form-grid">
            <label class="field">
              <span>{{ $t('profile.add.route') }}</span>
              <select v-model="draft.route" @change="addError = ''">
                <option v-for="row in ROUTES" :key="row.route" :value="row.route">{{ routeLabel(row.route) }}</option>
              </select>
            </label>
            <label class="field">
              <span>{{ $t('profile.add.label') }}</span>
              <input
                v-model="draft.label"
                type="text"
                maxlength="80"
                autocomplete="off"
                :placeholder="routeLabel(draft.route)"
                @input="addError = ''"
              />
            </label>
            <label v-if="draftRoute.card" class="field">
              <span>{{ $t('profile.add.last4') }}</span>
              <input
                :value="draft.last4"
                type="text"
                inputmode="numeric"
                pattern="\d{4}"
                autocomplete="off"
                placeholder="1234"
                @input="onLast4Input"
              />
            </label>
          </div>
          <p class="muted small">
            {{ draftRoute.card ? $t('profile.add.last4Hint') : $t('profile.add.walletHint') }}
          </p>
          <div class="method-form-checks">
            <label class="method-toggle">
              <input v-model="draft.connected" type="checkbox" />
              <span>{{ $t('profile.connected') }}</span>
            </label>
            <label class="method-toggle">
              <input v-model="draft.is_default" type="checkbox" />
              <span>{{ $t('profile.add.makeDefault') }}</span>
            </label>
          </div>
          <p v-if="addError" class="profile-note bad" role="alert">{{ addError }}</p>
          <div class="method-form-actions">
            <button type="submit" class="btn primary small" :disabled="addBusy">{{ $t('profile.add.submit') }}</button>
            <button type="button" class="btn ghost small" :disabled="addBusy" @click="adding = false">{{ $t('profile.add.cancel') }}</button>
          </div>
        </form>
      </section>

      <section class="card">
        <h2>{{ $t('profile.rank') }}</h2>
        <p class="muted small">{{ $t('profile.rankHint') }}</p>
        <fieldset class="benefit-pick">
          <legend>{{ $t('profile.topBenefit') }}</legend>
          <label v-for="kind in BENEFIT_KINDS" :key="kind" class="benefit-option" :class="{ active: topBenefit === kind }">
            <input v-model="topBenefit" type="radio" name="top-benefit" :value="kind" />
            <span>
              <strong>{{ benefitLabel(kind) }}</strong>
              <small class="muted">{{ $t('profile.earnedWith', { routes: earnedWith(kind) }) }}</small>
            </span>
          </label>
        </fieldset>
        <p class="muted small">{{ $t('profile.rankOrder') }}</p>
        <ol class="rank-list">
          <li v-for="(kind, index) in rank" :key="kind">
            <span class="rank-index">{{ index + 1 }}</span>
            <span>{{ benefitLabel(kind) }}</span>
            <button type="button" :aria-label="$t('profile.moveUp')" :disabled="index === 0" @click="move(index, -1)">
              <Icon :icon="ArrowUp01Icon" :size="16" />
            </button>
            <button type="button" :aria-label="$t('profile.moveDown')" :disabled="index === rank.length - 1" @click="move(index, 1)">
              <Icon :icon="ArrowDown01Icon" :size="16" />
            </button>
          </li>
        </ol>
      </section>

      <section v-if="profile.benefit_balances?.length" class="card">
        <h2>{{ $t('profile.earned') }}</h2>
        <ul class="split-list">
          <li v-for="row in profile.benefit_balances" :key="row.kind">
            <strong>{{ benefitLabel(row.kind) }}</strong>
            <span>{{ row.amount }}</span>
          </li>
        </ul>
      </section>

      <p v-if="notice" class="profile-note">{{ notice }}</p>
      <p v-if="error" class="profile-note bad">{{ error }}</p>
      <button type="button" class="btn primary" :disabled="busy" @click="save">{{ $t('profile.save') }}</button>
    </template>
    <p v-else-if="error" class="profile-note bad">{{ error }}</p>
  </main>
</template>
