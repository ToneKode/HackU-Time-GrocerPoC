<script setup>
// Full-width "review your basket" sheet shown when the agent returns a READY preview.
// The shopper can remove items, change quantities, swap an item for an alternative, or add products.
// Confirm -> the parent asks the agent to check the policy and pay for this (possibly edited) basket.
import { ref, computed, watch, nextTick, onBeforeUnmount } from 'vue'
import { money } from '../lib/format.js'
import { categoryArt } from '../lib/productArt.js'
import { storeName, productName, isEnglish } from '../i18n/index.js'
import MerchantLogo from './shop/MerchantLogo.vue'
import QtyStepper from './shop/QtyStepper.vue'
import ProductPicker from './ProductPicker.vue'
import Icon from './shop/Icon.vue'
import {
  Cancel01Icon, CheckmarkCircle02Icon, Delete02Icon, PlusSignIcon,
  ArrowDataTransferHorizontalIcon, AlertCircleIcon,
} from '@hugeicons/core-free-icons'

const props = defineProps({
  plan: { type: Object, default: null }, // READY ActionPlan, or null when closed
  busy: Boolean,
})
// confirm(items): items is [{ sku, qty }] when the basket was edited, or null when unchanged.
const emit = defineEmits(['confirm', 'close'])

// Same rule as the mall: delivery is free from the threshold, HK$30 below it.
const DELIVERY_FEE = 30

// One shape for both a basket run (plan.lines) and a one-product run (plan.quote.line_items).
function itemsFrom(plan) {
  if (plan.lines?.length) {
    return plan.lines.map((l) => ({
      sku: l.sku, name: l.name, merchant: l.merchant, category: l.category, sellPoint: l.sell_point,
      qty: l.qty, unitPrice: l.unit_price, reason: l.product_reason, image: '',
    }))
  }
  return (plan.quote?.line_items ?? []).map((l) => ({
    sku: l.sku, name: l.name, merchant: l.merchant, category: l.category,
    sellPoint: plan.product?.id === l.sku ? plan.product.sell_point : '',
    qty: l.qty, unitPrice: l.unit_price, reason: '',
    image: plan.product?.id === l.sku ? plan.product.image_url : '',
  }))
}

// ---- Editable copy of the basket ----
const items = ref([])
const original = ref({}) // sku -> qty as the agent proposed
const counts = (list) => Object.fromEntries(list.map((i) => [i.sku, i.qty]))
const edited = computed(() => JSON.stringify(counts(items.value)) !== JSON.stringify(original.value))
const inBasket = computed(() => counts(items.value))

function setQty(item, qty) {
  if (qty <= 0) remove(item)
  else item.qty = Math.min(qty, 99)
}
function remove(item) {
  items.value = items.value.filter((i) => i !== item)
}

const storeCount = computed(() => new Set(items.value.map((i) => i.merchant)).size)
const quote = computed(() => props.plan?.quote ?? {})
const subtotal = computed(() => Math.round(items.value.reduce((sum, i) => sum + i.unitPrice * i.qty, 0) * 100) / 100)
const delivery = computed(() => {
  if (!edited.value) return quote.value.shipping_fee ?? 0
  const threshold = quote.value.free_shipping_threshold ?? 400
  return subtotal.value >= threshold ? 0 : DELIVERY_FEE
})
const total = computed(() => (edited.value ? subtotal.value + delivery.value : quote.value.total_landed_cost))

// ---- Product picker (add, or swap one item) ----
const pickerOpen = ref(false)
const replacing = ref(null)
function openPicker(item = null) {
  replacing.value = item
  pickerOpen.value = true
}
function closePicker() {
  pickerOpen.value = false
  replacing.value = null
}
function onPick(product) {
  const existing = items.value.find((i) => i.sku === product.id)
  if (replacing.value) {
    // Swap: the new product takes the old one's place and quantity
    // (merged into the existing line if it's already in the basket).
    const old = replacing.value
    if (existing && existing !== old) {
      existing.qty = Math.min(existing.qty + old.qty, 99)
      items.value = items.value.filter((i) => i !== old)
    } else {
      items.value.splice(items.value.indexOf(old), 1, fromProduct(product, old.qty))
    }
    closePicker()
  } else if (existing) {
    existing.qty = Math.min(existing.qty + 1, 99)
  } else {
    items.value.push(fromProduct(product, 1))
  }
}
function fromProduct(p, qty) {
  return {
    sku: p.id, name: p.name, merchant: p.merchant, category: p.category, sellPoint: p.sell_point,
    qty, unitPrice: p.price, reason: '', image: p.image_url, added: true,
  }
}

function confirm() {
  if (!items.value.length) return
  emit('confirm', edited.value ? items.value.map((i) => ({ sku: i.sku, qty: i.qty })) : null)
}

const track = ref(null)

// ---- Open / close ----
const confirmButton = ref(null)
function onKey(event) {
  if (event.key !== 'Escape' || props.busy) return
  if (pickerOpen.value) closePicker()
  else emit('close')
}
watch(
  () => props.plan,
  async (plan) => {
    document.documentElement.classList.toggle('modal-open', Boolean(plan))
    if (plan) {
      items.value = itemsFrom(plan)
      original.value = counts(items.value)
      window.addEventListener('keydown', onKey)
      await nextTick()
      if (track.value) track.value.scrollLeft = 0
      confirmButton.value?.focus()
    } else {
      closePicker()
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
      <div v-if="plan" class="sheet-backdrop" @click="!busy && !pickerOpen && emit('close')" />
    </Transition>
    <Transition name="sheet-up">
      <section v-if="plan" class="basket-sheet" role="dialog" aria-modal="true" aria-labelledby="basket-title">
        <header class="basket-head">
          <div>
            <h2 id="basket-title">{{ $t('basket.title') }}</h2>
            <p class="muted small">
              {{ $t('basket.items', items.length) }} · {{ $t('basket.stores', storeCount) }}
              <span v-if="edited" class="basket-edited">· {{ $t('basket.edited') }}</span>
            </p>
          </div>
          <button type="button" class="basket-close" :aria-label="$t('basket.close')" :disabled="busy" @click="emit('close')">
            <Icon :icon="Cancel01Icon" :size="20" />
          </button>
        </header>

        <ul ref="track" class="basket-track">
          <li v-for="item in items" :key="item.sku" class="basket-item">
            <div class="basket-img" :style="{ background: categoryArt(item.category).tint }">
              <img v-if="item.image" :src="item.image" :alt="item.name" loading="lazy" />
              <span v-else class="basket-emoji" aria-hidden="true">{{ categoryArt(item.category).emoji }}</span>
              <span v-if="item.added" class="basket-added">{{ $t('basket.added') }}</span>
              <button type="button" class="basket-remove" :aria-label="$t('basket.remove', { name: productName({ id: item.sku, name: item.name }) })" @click="remove(item)">
                <Icon :icon="Delete02Icon" :size="18" />
              </button>
            </div>
            <div class="basket-store">
              <MerchantLogo :name="item.merchant" :size="18" />
              <span>{{ storeName(item.merchant) }}</span>
            </div>
            <!-- Product names come from the mall: plain text only. -->
            <h3 class="basket-name">{{ productName({ id: item.sku, name: item.name }) }}</h3>
            <span v-if="item.sellPoint && $te(`basket.sellPoint.${item.sellPoint}`)" class="basket-badge">
              {{ $t(`basket.sellPoint.${item.sellPoint}`) }}
            </span>
            <!-- The agent writes reasons in English; in Chinese the sell-point badge says the same. -->
            <p v-if="item.reason && isEnglish()" class="basket-reason">{{ item.reason }}</p>
            <button type="button" class="link-btn basket-swap" @click="openPicker(item)">
              <Icon :icon="ArrowDataTransferHorizontalIcon" :size="16" /> {{ $t('basket.alternatives') }}
            </button>
            <div class="basket-price">
              <QtyStepper :model-value="item.qty" @update:model-value="setQty(item, $event)" />
              <strong>{{ money(item.unitPrice * item.qty) }}</strong>
            </div>
          </li>

          <li class="basket-add-card">
            <button type="button" @click="openPicker()">
              <span class="basket-add-icon"><Icon :icon="PlusSignIcon" :size="26" :stroke-width="2" /></span>
              <strong>{{ $t('basket.addProduct') }}</strong>
              <span class="muted small">{{ $t('basket.addHint') }}</span>
            </button>
          </li>
        </ul>

        <footer class="basket-foot">
          <dl class="basket-sum">
            <div><dt>{{ $t('basket.subtotal') }}</dt><dd>{{ money(edited ? subtotal : quote.subtotal) }}</dd></div>
            <div><dt>{{ $t('basket.delivery') }}</dt><dd>{{ delivery ? money(delivery) : $t('basket.free') }}</dd></div>
            <div class="basket-total"><dt>{{ $t('basket.total') }}</dt><dd>{{ money(total) }}</dd></div>
          </dl>
          <div class="basket-actions">
            <p v-if="!items.length" class="basket-next error-text small">
              <Icon :icon="AlertCircleIcon" :size="16" /> {{ $t('basket.empty') }}
            </p>
            <p v-else-if="edited" class="basket-next muted small">
              <Icon :icon="AlertCircleIcon" :size="16" /> {{ $t('basket.editedNote') }}
            </p>
            <p v-else class="basket-next muted small">
              <Icon :icon="CheckmarkCircle02Icon" :size="16" /> {{ $t('basket.nextStep') }}
            </p>
            <div class="basket-buttons">
              <button type="button" class="btn-soft" :disabled="busy" @click="emit('close')">{{ $t('basket.notNow') }}</button>
              <button ref="confirmButton" type="button" class="btn-primary" :disabled="busy || !items.length" @click="confirm">
                {{ busy ? $t('basket.confirming') : $t('basket.confirm', { amount: money(total) }) }}
              </button>
            </div>
          </div>
        </footer>
      </section>
    </Transition>

    <ProductPicker :open="pickerOpen" :replacing="replacing" :in-basket="inBasket" @pick="onPick" @close="closePicker" />
  </Teleport>
</template>
