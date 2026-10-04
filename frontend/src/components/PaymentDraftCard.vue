<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { money } from '../lib/format.js'
import { storeName } from '../i18n/index.js'

const props = defineProps({
  draft: { type: Object, required: true },
  busy: Boolean,
})
const emit = defineEmits(['authorize'])
const { t, te } = useI18n()

const paid = computed(() => props.draft.status === 'CAPTURED')
const railLabel = computed(() => {
  const rail = props.draft.rail || ''
  const key = `agentCards.rails.${rail}`
  return te(key) ? t(key) : rail
})
</script>

<template>
  <section class="card approval" :class="{ closed: paid }">
    <div class="approval-head">
      <h2>{{ $t('agentCards.payTitle') }}</h2>
      <span class="pill">{{ paid ? $t('agentCards.escalation.APPROVED') : $t('agentCards.payWaiting') }}</span>
    </div>

    <dl class="rows">
      <dt>{{ $t('agentCards.amount') }}</dt><dd class="total">{{ money(draft.amount) }}</dd>
      <dt>{{ $t('agentCards.merchant') }}</dt><dd>{{ storeName(draft.merchant) }}</dd>
      <dt>{{ $t('agentCards.rail') }}</dt><dd>{{ railLabel }}</dd>
    </dl>
    <p v-if="draft.step_up_required" class="muted step-up-note">{{ $t('agentCards.stepUp') }}</p>

    <div class="actions single">
      <button type="button" class="btn primary" :disabled="busy || paid" @click="emit('authorize')">
        {{ $t('agentCards.approvePay') }}
      </button>
    </div>
  </section>
</template>
