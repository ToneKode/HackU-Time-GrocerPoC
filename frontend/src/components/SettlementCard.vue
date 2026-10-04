<script setup>
import GiftList from './GiftList.vue'
import { giftLines, paidLines } from '../lib/format.js'
import { ref } from 'vue'
import { money, reasonParts } from '../lib/format.js'

defineProps({
  settlement: { type: Object, required: true },
  canEdit: Boolean,
  canPay: Boolean,
})
const emit = defineEmits(['edit', 'pay'])
const open = ref(false)
</script>

<template>
  <section class="card settlement-card">
    <button type="button" class="settlement-total" :aria-expanded="open" @click="open = !open">
      <span>{{ $t('agentCards.finalPay') }}</span>
      <strong>{{ money(settlement.total) }}</strong>
    </button>
    <ul v-if="open" class="split-list">
      <li v-for="group in settlement.merchants || []" :key="group.merchant">
        <strong>{{ group.merchant }}</strong>
        <span>{{ money(group.payable) }}</span>
        <p class="muted small">
          {{ group.payment?.label }}
          <template v-if="group.payment?.amount != null"> · {{ money(group.payment.amount) }}</template>
        </p>
        <div v-if="group.because" class="benefit-rationale" data-testid="benefit-rationale"><p v-for="part in reasonParts(group.because)" :key="part" class="muted small">{{ part }}</p></div>
        <p v-for="line in paidLines(group.lines)" :key="line.sku" class="muted small">
          {{ line.name }} × {{ line.qty }}
        </p>
      </li>
    </ul>
    <GiftList :gifts="giftLines(settlement)" />
    <div class="actions">
      <button v-if="canEdit" type="button" class="btn" @click="emit('edit')">{{ $t('agentCards.sheetTitle') }}</button>
      <button v-if="canPay" type="button" class="btn primary" @click="emit('pay')">{{ $t('agentCards.approvePay') }}</button>
    </div>
  </section>
</template>
