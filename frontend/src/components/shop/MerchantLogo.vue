<script setup>
import { computed } from 'vue'
import { merchantByName } from '../../data/catalog.js'
import { storeName } from '../../i18n/index.js'

const props = defineProps({ name: { type: String, required: true }, size: { type: Number, default: 20 } })
const merchant = computed(() => merchantByName[props.name] ?? { short: props.name[0], color: '#888' })
</script>

<template>
  <span
    class="merchant-logo"
    :style="{ background: merchant.color, width: size + 'px', height: size + 'px', fontSize: size * 0.42 + 'px' }"
    :title="storeName(name)"
  >{{ merchant.short }}</span>
</template>
