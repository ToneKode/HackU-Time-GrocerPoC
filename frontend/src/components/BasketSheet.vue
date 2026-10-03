<script setup>
import { money } from '../lib/format.js'
import Icon from './shop/Icon.vue'
import { Cancel01Icon, MinusSignIcon, PlusSignIcon } from '@hugeicons/core-free-icons'

defineProps({
  lines: { type: Array, default: () => [] },
  busy: Boolean,
})
const emit = defineEmits(['close', 'confirm', 'remove', 'qty'])

function mark(name) {
  const text = String(name || '?').trim()
  return text.slice(0, 1).toUpperCase()
}
</script>

<template>
  <div class="sheet-back" role="dialog" aria-modal="true" :aria-label="$t('agentCards.sheetTitle')">
    <header class="sheet-bar">
      <div>
        <p class="sheet-kicker">{{ $t('agentCards.sheetKicker') }}</p>
        <h2>{{ $t('agentCards.sheetTitle') }}</h2>
      </div>
      <button type="button" class="tile-x" :aria-label="$t('menu.close')" @click="emit('close')">
        <Icon :icon="Cancel01Icon" :size="18" />
      </button>
    </header>
    <p class="sheet-hint">{{ $t('agentCards.sheetHint') }}</p>

    <div v-if="!lines.length" class="sheet-empty">{{ $t('agentCards.emptyBasket') }}</div>
    <div v-else class="tile-row">
      <article v-for="line in lines" :key="line.sku" class="product-tile">
        <button type="button" class="tile-x" :aria-label="$t('agentCards.removeItem', { name: line.name })" @click="emit('remove', line.sku)">
          <Icon :icon="Cancel01Icon" :size="16" />
        </button>
        <img v-if="line.image_url" class="tile-photo" :src="line.image_url" :alt="line.name" />
        <div v-else class="tile-photo tile-mark" aria-hidden="true">{{ mark(line.name) }}</div>
        <div class="tile-step">
          <button type="button" :aria-label="$t('card.removeOne')" :disabled="line.qty <= 1" @click="emit('qty', line.sku, line.qty - 1)">
            <Icon :icon="MinusSignIcon" :size="16" :stroke-width="2.2" />
          </button>
          <span>{{ line.qty }}</span>
          <button type="button" :aria-label="$t('card.addOne')" @click="emit('qty', line.sku, line.qty + 1)">
            <Icon :icon="PlusSignIcon" :size="16" :stroke-width="2.2" />
          </button>
        </div>
        <strong class="tile-name">{{ line.name }}</strong>
        <span class="muted small">{{ line.merchant }}</span>
        <span class="tile-price">{{ money(line.line_total) }}</span>
      </article>
    </div>

    <footer class="sheet-foot">
      <button type="button" class="btn primary sheet-confirm" :disabled="busy || !lines.length" @click="emit('confirm')">
        {{ $t('agentCards.confirmBasket') }}
      </button>
    </footer>
  </div>
</template>
