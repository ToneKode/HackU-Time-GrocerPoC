<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { session } from '../stores/auth.js'
import * as api from '../lib/api.js'
import { money } from '../lib/format.js'
import Icon from '../components/shop/Icon.vue'
import { ArrowDown01Icon, ArrowUp01Icon } from '@hugeicons/core-free-icons'

const { t, te } = useI18n()
const profile = ref(null)
const rank = ref([])
const methods = ref([])
const error = ref('')
const notice = ref('')
const busy = ref(false)

function benefitLabel(kind) {
  const key = `agentCards.benefits.${kind}`
  return te(key) ? t(key) : kind
}

async function load() {
  if (!session.user?.id) return
  error.value = ''
  try {
    const body = await api.getProfile(session.user.id)
    profile.value = body
    rank.value = [...(body.benefit_rank || [])]
    methods.value = (body.payment_methods || []).map((row) => ({ ...row }))
  } catch (err) {
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
  busy.value = true
  notice.value = ''
  error.value = ''
  try {
    const body = await api.savePreferences(session.user.id, {
      benefit_rank: rank.value,
      methods: methods.value.map((row) => ({ id: row.id, connected: row.connected })),
    })
    profile.value = body
    rank.value = [...body.benefit_rank]
    methods.value = body.payment_methods.map((row) => ({ ...row }))
    notice.value = t('profile.saved')
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

onMounted(load)
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

      <section class="card">
        <h2>{{ $t('profile.methods') }}</h2>
        <p class="muted small">{{ $t('profile.methodsHint') }}</p>
        <ul class="method-list">
          <li v-for="method in methods" :key="method.id">
            <div>
              <strong>{{ method.label }}</strong>
              <p class="muted small">
                {{ method.route }}
                <template v-if="method.last4"> · {{ method.last4 }}</template>
              </p>
            </div>
            <label class="method-toggle">
              <input v-model="method.connected" type="checkbox" @change="notice = ''" />
              <span>{{ $t('profile.connected') }}</span>
            </label>
          </li>
        </ul>
      </section>

      <section class="card">
        <h2>{{ $t('profile.rank') }}</h2>
        <p class="muted small">{{ $t('profile.rankHint') }}</p>
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
