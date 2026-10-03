<script setup>
import { computed } from 'vue'
import contract from '../../contract.json'
import { money, clock } from '../lib/format.js'
import { storeName, policyReason } from '../i18n/index.js'

const props = defineProps({
  escalation: { type: Object, required: true },
  busy: Boolean,
})
const emit = defineEmits(['decide'])

const screen = contract.screens.approval
const canDecide = computed(
  () => props.escalation.status === 'PENDING' && props.escalation.remaining_seconds > 0 && !props.busy,
)
const progress = computed(() => (props.escalation.remaining_seconds / props.escalation.ttl_seconds) * 100)
</script>

<template>
  <section class="card approval" :class="{ closed: escalation.status !== 'PENDING' }">
    <div class="approval-head">
      <h2>{{ $t('agentCards.approvalTitle') }}</h2>
      <span class="pill">{{ $t(`agentCards.escalation.${escalation.status}`) }}</span>
    </div>

    <div class="timer" :class="{ low: escalation.remaining_seconds <= 60 }">
      {{ clock(escalation.remaining_seconds) }}
    </div>
    <div class="timer-bar"><div :style="{ width: progress + '%' }" /></div>

    <dl class="rows">
      <dt>{{ $t('agentCards.amount') }}</dt><dd class="total">{{ money(escalation.amount) }}</dd>
      <dt>{{ $t('agentCards.merchant') }}</dt><dd>{{ storeName(escalation.merchant) }}</dd>
      <dt>{{ $t('agentCards.reason') }}</dt><dd>{{ policyReason(escalation.reason) }}</dd>
    </dl>

    <div class="actions">
      <button
        v-for="button in screen.buttons"
        :key="button.decision"
        class="btn"
        :class="button.decision === 'APPROVE' ? 'primary' : 'danger'"
        :disabled="!canDecide"
        @click="emit('decide', button.decision)"
      >
        {{ button.decision === 'APPROVE' ? $t('agentCards.approve') : $t('agentCards.refuse') }}
      </button>
    </div>
  </section>
</template>
