<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { clock, money } from '../lib/format.js'
import Icon from './shop/Icon.vue'
import { Cancel01Icon } from '@hugeicons/core-free-icons'

const props = defineProps({
  plan: { type: Object, required: true },
  seconds: { type: Number, default: 600 },
  busy: Boolean,
})
const emit = defineEmits(['close', 'approve'])
const { t, te } = useI18n()
const more = ref(false)

const settlement = computed(() => props.plan.settlement || {})
const rows = computed(() => {
  const groups = settlement.value.merchants || []
  const flat = groups.flatMap((group) => group.lines || [])
  return flat.length ? flat : props.plan.lines || []
})
const expired = computed(() => props.seconds <= 0)

function benefitLabel(kind) {
  const key = `agentCards.benefits.${kind}`
  return te(key) ? t(key) : kind
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

        <ul class="receipt-lines">
          <li v-for="line in rows" :key="`${line.merchant}-${line.sku}`" class="receipt-line">
            <img v-if="line.image_url" class="receipt-photo" :src="line.image_url" :alt="line.name" />
            <div v-else class="receipt-photo tile-mark" aria-hidden="true">{{ mark(line.name) }}</div>
            <div>
              <strong>{{ line.name }}</strong>
              <p class="muted small">{{ line.merchant }} · {{ $t('agentCards.qty', { n: line.qty }) }}</p>
            </div>
            <span>{{ money(line.line_total) }}</span>
          </li>
        </ul>

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

        <button type="button" class="link-btn" :aria-expanded="more" @click="more = !more">
          {{ more ? $t('agentCards.hideInfo') : $t('agentCards.moreInfo') }}
        </button>
        <ul v-if="more" class="split-list">
          <li v-for="group in settlement.merchants || []" :key="group.merchant">
            {{ $t('agentCards.paidBy', {
              amount: money(group.payment?.amount),
              label: group.payment?.label || group.payment?.route,
              merchant: group.merchant,
            }) }}
            <span v-if="group.payment?.last4" class="muted"> · {{ group.payment.last4 }}</span>
            <p v-if="group.because" class="muted small">{{ group.because }}</p>
          </li>
        </ul>
        <p v-if="plan.payment_draft?.step_up_required" class="muted step-up-note">{{ $t('agentCards.stepUp') }}</p>
      </article>
    </div>

    <footer class="sheet-foot">
      <button type="button" class="btn primary sheet-confirm" :disabled="busy || expired" @click="emit('approve')">
        {{ $t('agentCards.approvePay') }}
      </button>
    </footer>
  </div>
</template>
