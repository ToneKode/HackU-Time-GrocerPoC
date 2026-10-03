<script setup>
// Chat with the shopping agent. Each request is a user message; the agent replies with a
// message that carries the ActionPlan (order, approval card, steps). Settings live in a sidebar.
import { ref, reactive, computed, nextTick, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import contract from '../../contract.json'
import * as api from '../lib/api.js'
import { money } from '../lib/format.js'
import { productName, storeName, policyReason } from '../i18n/index.js'
import { session } from '../stores/auth.js'
import OrderCard from '../components/OrderCard.vue'
import ApprovalCard from '../components/ApprovalCard.vue'
import TraceList from '../components/TraceList.vue'
import BudgetCard from '../components/BudgetCard.vue'
import RulesCard from '../components/RulesCard.vue'
import ComparisonCard from '../components/ComparisonCard.vue'
import Icon from '../components/shop/Icon.vue'
import {
  AiMagicIcon, ArrowUp02Icon, SlidersHorizontalIcon, Cancel01Icon, Delete02Icon, ArrowDown01Icon, ArrowUp01Icon,
} from '@hugeicons/core-free-icons'

const { t, tm, rt } = useI18n()
const route = useRoute()
const router = useRouter()

// ---- Messages ----
// { id, role: 'user' | 'agent', kind: 'text' | 'thinking' | 'plan' | 'error', text?, plan?, request? }
const messages = ref([])
const escalations = reactive({}) // escalation_id -> live Escalation (polled)
const openSteps = reactive({}) // message id -> steps expanded
let nextId = 1
const busy = ref(false)
const deciding = ref(false)

const scroller = ref(null)
async function scrollToBottom() {
  await nextTick()
  scroller.value?.scrollTo({ top: scroller.value.scrollHeight, behavior: 'smooth' })
}

function push(message) {
  const m = { id: nextId++, ...message }
  messages.value.push(m)
  scrollToBottom()
  return m
}
function replace(target, message) {
  const i = messages.value.indexOf(target)
  if (i >= 0) messages.value.splice(i, 1, { ...target, ...message })
  scrollToBottom()
}

// ---- Composer ----
const draft = ref('')
const input = ref(null)
const suggestions = computed(() => tm('agentChat.suggestions').map((s) => rt(s)))

function autosize() {
  const el = input.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 140) + 'px'
}

function onKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    send()
  }
}

onMounted(() => {
  const intent = String(route.query.intent || '').trim()
  if (!intent) return
  router.replace({ name: 'agent' })
  send(intent)
})

function send(text = draft.value) {
  const intent = text.trim()
  if (!intent || busy.value) return
  draft.value = ''
  nextTick(autosize)
  const request = { intent, monthly_spent: Number(monthlySpent.value) || 0 }
  push({ role: 'user', kind: 'text', text: intent })
  runAgent(request)
}

// ---- Polling the escalation every second while it is PENDING ----
const POLL_MS = contract.calls.read_escalation.poll_every_seconds * 1000
let pollTimer = null
let pollToken = 0

function startPolling(id) {
  stopPolling()
  const token = ++pollToken
  pollTimer = setInterval(async () => {
    try {
      const esc = await api.getEscalation(id)
      if (token !== pollToken) return
      escalations[id] = esc
      if (esc.status !== 'PENDING') {
        stopPolling()
        if (esc.status === 'EXPIRED') push({ role: 'agent', kind: 'text', text: t('agentChat.expired') })
      }
    } catch (e) {
      if (token !== pollToken) return
      stopPolling()
      push({ role: 'agent', kind: 'error', text: t('agentChat.error', { message: e.message }) })
    }
  }, POLL_MS)
}
function stopPolling() {
  clearInterval(pollTimer)
  pollTimer = null
  pollToken++
}
onBeforeUnmount(stopPolling)

// ---- Agent calls ----
async function runAgent(request, escalationId) {
  stopPolling()
  busy.value = true
  const thinking = push({ role: 'agent', kind: 'thinking' })
  try {
    const plan = await api.sendIntent({ ...request, escalation_id: escalationId })
    if (plan.escalation) escalations[plan.escalation.escalation_id] = plan.escalation
    replace(thinking, { kind: 'plan', plan, request })
    if (plan.status === 'ESCALATED' && plan.escalation?.status === 'PENDING') startPolling(plan.escalation.escalation_id)
  } catch (e) {
    replace(thinking, { kind: 'error', text: t('agentChat.error', { message: e.message }) })
  } finally {
    busy.value = false
  }
}

// Approve -> ask the agent again with the same request + escalation_id.
// Refuse -> the agent confirms the cancellation; it is not called again.
async function onDecide(message, decision) {
  const id = message.plan.escalation.escalation_id
  stopPolling()
  deciding.value = true
  try {
    const esc = await api.decide(id, decision)
    escalations[id] = esc
    if (esc.status === 'APPROVED') {
      push({ role: 'agent', kind: 'text', text: t('agentChat.approvedNote') })
      await runAgent(message.request, id)
    } else if (esc.status === 'REFUSED') {
      push({ role: 'agent', kind: 'text', text: t('agentChat.refused') })
    } else if (esc.status === 'EXPIRED') {
      push({ role: 'agent', kind: 'text', text: t('agentChat.expired') })
    } else {
      startPolling(id)
    }
  } catch (e) {
    push({ role: 'agent', kind: 'error', text: t('agentChat.error', { message: e.message }) })
  } finally {
    deciding.value = false
  }
}

// The sentence the agent says for a plan.
function summary(plan) {
  if (plan.reply) return plan.reply
  if (plan.question) return plan.question
  const product = plan.product ? productName(plan.product) : ''
  const store = plan.product ? storeName(plan.product.merchant) : ''
  const amount = money(plan.payment?.charged ?? plan.policy?.amount ?? plan.quote?.total_landed_cost)
  switch (plan.status) {
    case 'COMPLETED':
      return t('agentChat.done', { product, store, amount })
    case 'ESCALATED':
      return t('agentChat.needsApproval', { product, store, amount })
    case 'HALTED':
      return t('agentChat.halted', { reason: policyReason(plan.policy?.reason ?? '') })
    case 'FAILED':
      return t('agentChat.failed', { error: plan.payment?.error ?? '' })
    case 'ABORTED':
      return t('agentChat.refused')
    case 'NEEDS_INPUT':
      return t('agentChat.needsInput')
    default:
      return t('agentChat.ready', { product, store, amount })
  }
}

function llmSteps(plan) {
  return (plan.react || []).filter((step) => step.source === 'llm' && step.thought)
}

function clearChat() {
  stopPolling()
  messages.value = []
  for (const key of Object.keys(escalations)) delete escalations[key]
  for (const key of Object.keys(openSteps)) delete openSteps[key]
}

// ---- Sidebar: budget + settings ----
const sidebarOpen = ref(false) // phone drawer; always visible on desktop
const monthlySpent = ref(0)
const monthlyCap = contract.active_rules.find((r) => r.id === 'monthly_cap').amount
const latestPlan = computed(() => [...messages.value].reverse().find((m) => m.kind === 'plan')?.plan ?? null)
const budget = computed(() => {
  const policy = latestPlan.value?.policy
  const spent = policy?.monthly_spent ?? (Number(monthlySpent.value) || 0)
  const cap = policy?.monthly_cap ?? monthlyCap
  return {
    cap,
    spent,
    remaining: policy?.monthly_remaining ?? cap - spent,
    amount: policy?.amount ?? 0,
    status: policy?.status ?? null,
  }
})

const userInitial = computed(() => (session.user?.name?.charAt(0) || t('agentChat.you').charAt(0)).toUpperCase())
</script>

<template>
  <main class="agent-page">
    <!-- ================= Chat ================= -->
    <section class="chat">
      <header class="chat-head">
        <span class="chat-avatar agent"><Icon :icon="AiMagicIcon" :size="20" /></span>
        <div class="chat-head-text">
          <strong>{{ $t('agentChat.title') }}</strong>
          <span class="muted small"><i class="chat-online" /> {{ $t('agentChat.status') }}</span>
        </div>
        <button type="button" class="chat-head-btn chat-settings-btn" :aria-expanded="sidebarOpen" aria-controls="agent-sidebar" @click="sidebarOpen = true">
          <Icon :icon="SlidersHorizontalIcon" :size="18" /> <span>{{ $t('agentChat.settings') }}</span>
        </button>
      </header>

      <div ref="scroller" class="chat-messages" aria-live="polite">
        <!-- Welcome -->
        <div class="msg agent">
          <span class="chat-avatar agent"><Icon :icon="AiMagicIcon" :size="18" /></span>
          <div class="msg-body">
            <p class="bubble">{{ $t('agentChat.welcome') }}</p>
          </div>
        </div>

        <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
          <span v-if="m.role === 'agent'" class="chat-avatar agent"><Icon :icon="AiMagicIcon" :size="18" /></span>

          <div class="msg-body">
            <!-- user / plain agent text -->
            <p v-if="m.kind === 'text'" class="bubble">{{ m.text }}</p>
            <p v-else-if="m.kind === 'error'" class="bubble bubble-error">{{ m.text }}</p>

            <!-- typing indicator -->
            <p v-else-if="m.kind === 'thinking'" class="bubble bubble-thinking" :aria-label="$t('agentChat.thinking')">
              <span class="dots"><i /><i /><i /></span> {{ $t('agentChat.thinking') }}
            </p>

            <!-- agent result -->
            <template v-else-if="m.kind === 'plan'">
              <p v-for="(step, i) in llmSteps(m.plan)" :key="`${m.id}-thought-${i}`" class="bubble">{{ step.thought }}</p>
              <p class="bubble">{{ summary(m.plan) }}</p>
              <p v-if="m.plan.question && m.plan.reply" class="bubble">{{ m.plan.question }}</p>
              <OrderCard v-if="m.plan.payment || m.plan.lines?.length" :plan="m.plan" class="msg-card" />
              <ApprovalCard
                v-if="m.plan.status === 'ESCALATED' && escalations[m.plan.escalation.escalation_id]"
                :escalation="escalations[m.plan.escalation.escalation_id]"
                :busy="deciding || busy"
                class="msg-card"
                @decide="onDecide(m, $event)"
              />
              <button type="button" class="link-btn msg-steps-btn" :aria-expanded="Boolean(openSteps[m.id])" @click="openSteps[m.id] = !openSteps[m.id]">
                <Icon :icon="openSteps[m.id] ? ArrowUp01Icon : ArrowDown01Icon" :size="16" />
                {{ openSteps[m.id] ? $t('agentChat.hideSteps') : $t('agentChat.showSteps', { n: m.plan.audit_log.length }) }}
              </button>
              <TraceList v-if="openSteps[m.id]" :entries="m.plan.audit_log" class="msg-card" />
            </template>
          </div>

          <span v-if="m.role === 'user'" class="chat-avatar user" aria-hidden="true">{{ userInitial }}</span>
        </div>
      </div>

      <!-- Composer -->
      <form class="composer" @submit.prevent="send()">
        <div v-if="!messages.length" class="composer-suggestions">
          <button v-for="s in suggestions" :key="s" type="button" class="store-chip" :disabled="busy" @click="send(s)">{{ s }}</button>
        </div>
        <div class="composer-box">
          <textarea
            ref="input"
            v-model="draft"
            rows="1"
            :placeholder="$t('agentChat.placeholder')"
            :aria-label="$t('agentChat.placeholder')"
            @input="autosize"
            @keydown="onKeydown"
          />
          <button type="submit" class="composer-send" :disabled="busy || !draft.trim()" :aria-label="$t('agentChat.send')">
            <Icon :icon="ArrowUp02Icon" :size="20" :stroke-width="2.2" />
          </button>
        </div>
        <p class="composer-hint muted">{{ $t('agentChat.hint') }}</p>
      </form>
    </section>

    <!-- ================= Settings sidebar ================= -->
    <div v-if="sidebarOpen" class="agent-backdrop" @click="sidebarOpen = false" />
    <aside id="agent-sidebar" class="agent-sidebar" :class="{ open: sidebarOpen }" :aria-label="$t('agentChat.settings')">
      <div class="agent-sidebar-head">
        <strong>{{ $t('agentChat.settings') }}</strong>
        <button type="button" class="menu-close" :aria-label="$t('menu.close')" @click="sidebarOpen = false">
          <Icon :icon="Cancel01Icon" :size="18" />
        </button>
      </div>

      <BudgetCard :budget="budget" />

      <section class="card">
        <label class="field">
          <span>{{ $t('agentChat.spentLabel') }}</span>
          <input v-model.number="monthlySpent" type="number" min="0" step="0.01" />
        </label>
        <p class="muted small agent-hint">{{ $t('agentChat.spentHint') }}</p>
      </section>

      <RulesCard :rules="contract.active_rules" />
      <ComparisonCard :comparison="contract.comparison" />

      <button type="button" class="link-btn danger-text agent-clear" :disabled="!messages.length" @click="clearChat">
        <Icon :icon="Delete02Icon" :size="16" /> {{ $t('agentChat.clearChat') }}
      </button>
    </aside>
  </main>
</template>
