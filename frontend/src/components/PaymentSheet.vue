<script setup>
import GiftList from './GiftList.vue'
import { giftLines, paidLines } from '../lib/format.js'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { clock, money, reasonParts, lineArithmetic, lineReasons } from '../lib/format.js'
import Icon from './shop/Icon.vue'
import { Cancel01Icon } from '@hugeicons/core-free-icons'

const props = defineProps({
  plan: { type: Object, required: true },
  seconds: { type: Number, default: 600 },
  busy: Boolean,
  uncertain: Boolean,
  canRecover: Boolean,
  error: { type: String, default: '' },
})
const emit = defineEmits(['close', 'approve', 'recover'])
const { t, te } = useI18n()
const more = ref(false)

const settlement = computed(() => props.plan.settlement || {})
const rows = computed(() => {
  const groups = settlement.value.merchants || []
  const flat = groups.flatMap((group) => group.lines || [])
  return paidLines(flat.length ? flat : props.plan.lines)
})
const expired = computed(() => props.seconds <= 0)
const draft = computed(() => props.plan.payment_draft || null)
const meal = computed(() => props.plan.meal || null)
// Comparison of every connected method per merchant, from the meal optimiser.
const options = computed(() => {
  const out = {}
  for (const row of meal.value?.payment || []) out[row.merchant] = row.options || []
  return out
})

function benefitLabel(kind) {
  const key = `agentCards.benefits.${kind}`
  return te(key) ? t(key) : kind
}
function benefitText(list) {
  return (list || []).map((item) => `${benefitLabel(item.kind)} ${item.amount}`).join(' · ')
}
function mark(name) {
  return String(name || '?').trim().slice(0, 1).toUpperCase()
}
</script>

<template>
  <div class="sheet-back" role="dialog" aria-modal="true" :aria-label="$t('agentCards.paySheetTitle')">
    <header class="sheet-bar">
      <div>
        <p class="sheet-kicker">{{ $t('agentCards.payTimer') }}</p>
        <h2>{{ $t('agentCards.paySheetTitle') }}</h2>
      </div>
      <button type="button" class="tile-x" :aria-label="$t('menu.close')" @click="emit('close')">
        <Icon :icon="Cancel01Icon" :size="18" />
      </button>
    </header>

    <div class="receipt-wrap">
      <article class="receipt">
        <div class="receipt-top">
          <span class="stamp" :class="{ 'stamp-off': expired }">{{ clock(seconds) }}</span>
          <span class="muted small">{{ expired ? $t('agentCards.payExpired') : $t('agentCards.payWaiting') }}</span>
        </div>

        <p v-if="plan.policy?.status === 'PASS'" class="sheet-ok">{{ $t('agentCards.policyPassed') }}</p>

        <section class="pay-method">
          <p class="sheet-kicker">{{ $t('agentCards.payMethod') }}</p>
          <ul class="split-list">
            <li v-for="group in settlement.merchants || []" :key="group.merchant">
              <strong>{{ group.payment?.label || group.payment?.route }}</strong>
              <span v-if="group.payment?.last4" class="muted">•••• {{ group.payment.last4 }}</span>
              <span class="muted small">{{ $t('agentCards.routeLabel', { route: group.payment?.route }) }}</span>
              <span>{{ $t('agentCards.paidBy', {
                amount: money(group.payment?.amount),
                label: group.payment?.label || group.payment?.route,
                merchant: group.merchant,
              }) }}</span>
              <div v-if="group.because" class="benefit-rationale" data-testid="benefit-rationale"><p v-for="part in reasonParts(group.because)" :key="part" class="muted small">{{ part }}</p></div>
              <p v-if="options[group.merchant]?.length" class="muted small">
                {{ $t('agentCards.payOptions') }}
                <span v-for="option in options[group.merchant]" :key="option.route" class="pay-option">
                  {{ option.label }}: {{ benefitText(option.benefits) || $t('agentCards.noBenefit') }}<template v-if="option.discount"> · −{{ money(option.discount) }}</template>
                </span>
              </p>
            </li>
          </ul>
          <p v-if="draft" class="muted small">
            {{ $t('agentCards.draftLine', { id: draft.payment_id, rail: draft.rail || '-', amount: money(draft.amount) }) }}
          </p>
        </section>

        <ul class="receipt-lines">
          <li v-for="line in rows" :key="`${line.merchant}-${line.sku}`" class="receipt-line">
            <img v-if="line.image_url" class="receipt-photo" :src="line.image_url" :alt="line.name" />
            <div v-else class="receipt-photo tile-mark" aria-hidden="true">{{ mark(line.name) }}</div>
            <div>
              <strong>{{ line.name }}</strong>
              <p class="muted small">{{ line.merchant }} · {{ $t('agentCards.qty', { n: line.qty }) }}</p>
              <p class="muted small" data-testid="pack-arithmetic">{{ lineArithmetic(line) }}</p>
              <div v-if="more" class="receipt-item-reason" :data-sku="line.sku"><p v-for="part in lineReasons(line)" :key="part">{{ part }}</p></div>
            </div>
            <span>{{ money(line.line_total) }}</span>
          </li>
        </ul>

        <GiftList :gifts="giftLines(plan)" />

        <div class="perforation" />
        <dl class="receipt-totals">
          <div><dt>{{ $t('agentCards.subtotal') }}</dt><dd>{{ money(settlement.subtotal) }}</dd></div>
          <div v-if="settlement.discount"><dt>{{ $t('agentCards.discount') }}</dt><dd>−{{ money(settlement.discount) }}</dd></div>
          <div><dt>{{ $t('agentCards.tax') }}</dt><dd>{{ money(settlement.tax || 0) }}</dd></div>
          <div><dt>{{ $t('agentCards.shipping') }}</dt><dd>{{ money(settlement.shipping_fee || 0) }}</dd></div>
          <div class="receipt-final"><dt>{{ $t('agentCards.finalPay') }}</dt><dd>{{ money(settlement.total) }}</dd></div>
        </dl>

        <div v-if="settlement.benefits?.length" class="benefit-stub">
          <p class="sheet-kicker">{{ $t('agentCards.benefitsTitle') }}</p>
          <ul>
            <li v-for="benefit in settlement.benefits" :key="benefit.kind">
              <strong>{{ benefitLabel(benefit.kind) }}</strong>
              <span>{{ benefit.amount }}</span>
              <em>{{ benefit.detail }}</em>
            </li>
          </ul>
        </div>
        <ul v-if="meal?.warnings?.length" class="band-note band-under">
          <li v-for="text in meal.warnings" :key="text">{{ text }}</li>
        </ul>

        <button type="button" class="link-btn" :aria-expanded="more" @click="more = !more">
          {{ more ? $t('agentCards.hideInfo') : $t('agentCards.moreInfo') }}
        </button>
        <div v-if="more" class="muted small pay-why" data-testid="payment-rationale"><p v-for="part in reasonParts(plan.payment_reason || meal?.strategy)" :key="part">{{ part }}</p></div>
        <p v-if="draft?.step_up_required" class="muted step-up-note">{{ $t('agentCards.stepUp') }}</p>
        <p class="muted small">{{ $t('agentCards.approveHint') }}</p>
      </article>
    </div>

    <footer class="sheet-foot">
      <p v-if="error" class="sheet-alert" role="alert">{{ error }}</p>
      <button v-if="uncertain && canRecover" type="button" class="btn primary sheet-confirm" data-testid="recover-payment" :disabled="busy" @click="emit('recover')">{{ $t('agentCards.recoverPayment') }}</button>
      <button v-else type="button" class="btn primary sheet-confirm" :disabled="busy || expired || uncertain" @click="emit('approve')">
        {{ $t(error ? 'agentCards.retryPayment' : 'agentCards.approvePay') }}
      </button>
    </footer>
  </div>
</template>
