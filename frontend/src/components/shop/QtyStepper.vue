<script setup>
import { MinusSignIcon, PlusSignIcon } from '@hugeicons/core-free-icons'
import Icon from './Icon.vue'

const qty = defineModel({ type: Number, required: true })
</script>

<template>
  <div class="stepper">
    <button type="button" :aria-label="$t('card.removeOne')" @click="qty = qty - 1"><Icon :icon="MinusSignIcon" :size="16" :stroke-width="2.2" /></button>
    <span>{{ qty }}</span>
    <button type="button" :aria-label="$t('card.addOne')" @click="qty = qty + 1"><Icon :icon="PlusSignIcon" :size="16" :stroke-width="2.2" /></button>
  </div>
</template>
