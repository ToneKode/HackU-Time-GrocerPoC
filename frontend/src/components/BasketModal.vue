<script setup>
// Full-width "review your basket" sheet shown when the agent returns a READY preview.
// Confirm -> the parent asks the agent to run the policy check and payment for this basket.
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { money } from '../lib/format.js'
import { storeName } from '../i18n/index.js'
import MerchantLogo from './shop/MerchantLogo.vue'
import Icon from './shop/Icon.vue'
import { Cancel01Icon, ArrowLeft01Icon, ArrowRight01Icon, CheckmarkCircle02Icon } from '@hugeicons/core-free-icons'

const props = defineProps({
  plan: { type: Object, default: null }, // READY ActionPlan, or null when closed
  busy: Boolean,
})
const emit = defineEmits(['confirm', 'close'])

// Product pictures until the mall sends image_url: one picture + tint per category.
const CATEGORY_ART = {
  household: ['🧻', 'var(--tint-household)'],
  food: ['🍚', 'var(--tint-pantry)'],
  pantry: ['🍚', 'var(--tint-pantry)'],
  beverages: ['💧', 'var(--tint-drinks)'],
  drinks: ['💧', 'var(--tint-drinks)'],
  snacks: ['🥔', 'var(--tint-snacks)'],
  health: ['😷', 'var(--tint-health)'],
  'personal care': ['🧴', 'var(--tint-personal)'],
  personal: ['🧴', 'var(--tint-personal)'],
  baby: ['👶', 'var(--tint-baby)'],
  pets: ['🐕', 'var(--tint-fruit-veg)'],
  electronics: ['🎧', 'var(--tint-dairy)'],
  kitchen: ['🥡', 'var(--tint-pantry)'],
  dairy: ['🥛', 'var(--tint-dairy)'],
  'fruit-veg': ['🥦', 'var(--tint-fruit-veg)'],
}
const art = (category) => CATEGORY_ART[(category || '').toLowerCase()] ?? ['🛒', 'var(--surface-2)']

// One shape for both a basket run (plan.lines) and a one-product run (plan.quote.line_items).
const items = computed(() => {
  const plan = props.plan
  if (!plan) return []
  if (plan.lines?.length) {
    return plan.lines.map((l) => ({
      sku: l.sku, name: l.name, merchant: l.merchant, category: l.category, sellPoint: l.sell_point,
      qty: l.qty, unitPrice: l.unit_price, total: l.line_total, reason: l.product_reason, image: '',
    }))
  }
  return (plan.quote?.line_items ?? []).map((l) => ({
    sku: l.sku, name: l.name, merchant: l.merchant, category: l.category,
    sellPoint: plan.product?.id === l.sku ? plan.product.sell_point : '',
    qty: l.qty, unitPrice: l.unit_price, total: l.line_total, reason: '',
    image: plan.product?.id === l.sku ? plan.product.image_url : '',
  }))
})
const storeCount = computed(() => new Set(items.value.map((i) => i.merchant)).size)
const quote = computed(() => props.plan?.quote ?? {})

// ---- Horizontal scrolling ----
const track = ref(null)
const canLeft = ref(false)
const canRight = ref(false)
function updateArrows() {
  const el = track.value
  if (!el) return
  canLeft.value = el.scrollLeft > 4
  canRight.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 4
}
function scrollByCard(direction) {
  const el = track.value
  const card = el?.querySelector('.basket-item')
  if (!el || !card) return
  el.scrollBy({ left: direction * (card.offsetWidth + 14), behavior: 'smooth' })
}

// ---- Open / close ----
const confirmButton = ref(null)
function onKey(event) {
  if (event.key === 'Escape' && !props.busy) emit('close')
}
watch(
  () => props.plan,
  async (plan) => {
    document.documentElement.classList.toggle('modal-open', Boolean(plan))
    if (plan) {
      window.addEventListener('keydown', onKey)
      await nextTick()
      if (track.value) track.value.scrollLeft = 0
      updateArrows()
      confirmButton.value?.focus()
    } else {
      window.removeEventListener('keydown', onKey)
    }
  },
)
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  document.documentElement.classList.remove('modal-open')
})
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet-fade">
      <div v-if="plan" class="sheet-backdrop" @click="!busy && emit('close')" />
    </Transition>
    <Transition name="sheet-up">
      <section v-if="plan" class="basket-sheet" role="dialog" aria-modal="true" aria-labelledby="basket-title">
        <header class="basket-head">
          <div>
            <h2 id="basket-title">{{ $t('basket.title') }}</h2>
            <p class="muted small">
              {{ $t('basket.items', items.length) }} · {{ $t('basket.stores', storeCount) }}
            </p>
          </div>
          <div class="basket-head-actions">
            <button type="button" class="basket-arrow" :disabled="!canLeft" :aria-label="$t('basket.previous')" @click="scrollByCard(-1)">
              <Icon :icon="ArrowLeft01Icon" :size="18" />
            </button>
            <button type="button" class="basket-arrow" :disabled="!canRight" :aria-label="$t('basket.next')" @click="scrollByCard(1)">
              <Icon :icon="ArrowRight01Icon" :size="18" />
            </button>
            <button type="button" class="basket-close" :aria-label="$t('basket.close')" :disabled="busy" @click="emit('close')">
              <Icon :icon="Cancel01Icon" :size="20" />
            </button>
          </div>
        </header>

        <ul ref="track" class="basket-track" @scroll.passive="updateArrows">
          <li v-for="item in items" :key="item.sku" class="basket-item">
            <div class="basket-img" :style="{ background: art(item.category)[1] }">
              <img v-if="item.image" :src="item.image" :alt="item.name" loading="lazy" />
              <span v-else class="basket-emoji" aria-hidden="true">{{ art(item.category)[0] }}</span>
              <span v-if="item.qty > 1" class="basket-qty">×{{ item.qty }}</span>
            </div>
            <div class="basket-store">
              <MerchantLogo :name="item.merchant" :size="18" />
              <span>{{ storeName(item.merchant) }}</span>
            </div>
            <!-- Product names come from the mall: plain text only. -->
            <h3 class="basket-name">{{ item.name }}</h3>
            <span v-if="item.sellPoint && $te(`basket.sellPoint.${item.sellPoint}`)" class="basket-badge">
              {{ $t(`basket.sellPoint.${item.sellPoint}`) }}
            </span>
            <p v-if="item.reason" class="basket-reason">{{ item.reason }}</p>
            <div class="basket-price">
              <span class="muted small">{{ item.qty }} × {{ money(item.unitPrice) }}</span>
              <strong>{{ money(item.total) }}</strong>
            </div>
          </li>
        </ul>

        <footer class="basket-foot">
          <dl class="basket-sum">
            <div><dt>{{ $t('basket.subtotal') }}</dt><dd>{{ money(quote.subtotal) }}</dd></div>
            <div><dt>{{ $t('basket.delivery') }}</dt><dd>{{ quote.shipping_fee ? money(quote.shipping_fee) : $t('basket.free') }}</dd></div>
            <div class="basket-total"><dt>{{ $t('basket.total') }}</dt><dd>{{ money(quote.total_landed_cost) }}</dd></div>
          </dl>
          <div class="basket-actions">
            <p class="basket-next muted small">
              <Icon :icon="CheckmarkCircle02Icon" :size="16" /> {{ $t('basket.nextStep') }}
            </p>
            <div class="basket-buttons">
              <button type="button" class="btn-soft" :disabled="busy" @click="emit('close')">{{ $t('basket.notNow') }}</button>
              <button ref="confirmButton" type="button" class="btn-primary" :disabled="busy" @click="emit('confirm')">
                {{ busy ? $t('basket.confirming') : $t('basket.confirm', { amount: money(quote.total_landed_cost) }) }}
              </button>
            </div>
          </div>
        </footer>
      </section>
    </Transition>
  </Teleport>
</template>
