<script setup>
import { computed } from 'vue'
import { money } from '../lib/format.js'

// budget: { cap, spent, remaining, amount, status }
const props = defineProps({ budget: { type: Object, required: true } })

// Contract: on PASS/ESCALATE the remaining already subtracts this order; on HALT it doesn't.
const thisOrder = computed(() => {
  const { status, amount } = props.budget
  return status === 'PASS' || status === 'ESCALATE' ? amount : 0
})
const pct = (n) => Math.min(100, Math.max(0, (n / props.budget.cap) * 100)) + '%'
</script>

<template>
  <section class="card">
    <h2>{{ $t('agentCards.budgetTitle') }}</h2>
    <div class="budget-big">{{ money(budget.remaining) }} <span class="muted">{{ $t('agentCards.left') }}</span></div>
    <div class="bar">
      <div class="bar-spent" :style="{ width: pct(budget.spent) }" />
      <div class="bar-order" :style="{ width: pct(thisOrder) }" />
    </div>
    <dl class="rows">
      <dt>{{ $t('agentCards.cap') }}</dt><dd>{{ money(budget.cap) }}</dd>
      <dt><i class="dot dot-spent" />{{ $t('agentCards.spent') }}</dt><dd>{{ money(budget.spent) }}</dd>
      <template v-if="thisOrder">
        <dt><i class="dot dot-order" />{{ $t('agentCards.thisOrder') }}</dt><dd>{{ money(thisOrder) }}</dd>
      </template>
    </dl>
  </section>
</template>
