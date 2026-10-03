<script setup>
// Thin wrapper so every Hugeicon uses the same defaults.
import { HugeiconsIcon } from '@hugeicons/vue'

defineProps({
  icon: { type: [Array, Object], required: true },
  size: { type: Number, default: 20 },
  strokeWidth: { type: Number, default: 1.8 },
})
</script>

<template>
  <HugeiconsIcon :icon="icon" :size="size" :stroke-width="strokeWidth" color="currentColor" class="hi" aria-hidden="true" />
</template>
