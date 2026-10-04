<script setup>
import { money } from '../lib/format.js'
defineProps({ gifts: { type: Array, default: () => [] } })
</script>

<template>
  <section v-if="gifts.length" class="gift-list" data-testid="gift-list">
    <h3>Promotional gifts</h3>
    <ul class="basket-lines">
      <li v-for="(gift, index) in gifts" :key="`${gift.merchant}-${gift.sku}-${index}`" :data-sku="gift.sku" data-testid="gift-line">
        <strong>{{ gift.name || gift.sku }}</strong>
        <span class="muted"> · {{ gift.merchant }} · {{ gift.qty }} × {{ money(0) }}</span>
        <span class="pill pill-ok">Gift · {{ money(0) }}</span>
        <p v-if="gift.reason" class="muted small">{{ gift.reason }}</p>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.gift-list { margin: 16px 0; }
.gift-list h3 { font-size: 1rem; margin-bottom: 8px; }
</style>
