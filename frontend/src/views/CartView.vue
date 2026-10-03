<script setup>
import { ref, computed } from 'vue'
import { merchants } from '../data/catalog.js'
import { optimalMix, singleStoreTotals, mixSavings, sortedOffers } from '../lib/pricing.js'
import { money } from '../lib/format.js'
import { cartLines, cartCount, setQty, clearCart } from '../stores/shop.js'
import MerchantChips from '../components/shop/MerchantChips.vue'
import MerchantLogo from '../components/shop/MerchantLogo.vue'
import QtyStepper from '../components/shop/QtyStepper.vue'
import Icon from '../components/shop/Icon.vue'
import { productName, storeName } from '../i18n/index.js'
import {
  ArrowLeft01Icon, ShoppingCart01Icon, FlashIcon, Store01Icon, ArrowDownRight01Icon, Delete02Icon,
  ArrowDown01Icon, ArrowUp01Icon, AiMagicIcon,
} from '@hugeicons/core-free-icons'

const allowed = ref(merchants.map((m) => m.name))
const mode = ref('mix') // 'mix' | 'single'
const openStore = ref(null)

const mix = computed(() => optimalMix(cartLines.value, allowed.value))
const stores = computed(() => singleStoreTotals(cartLines.value, allowed.value))
const savings = computed(() => mixSavings(mix.value, stores.value))
</script>

<template>
  <main class="page cart">
    <RouterLink to="/" class="back-link"><Icon :icon="ArrowLeft01Icon" :size="16" /> {{ $t('cart.backHome') }}</RouterLink>

    <div class="cart-head">
      <h1>{{ $t('cart.title') }} <span v-if="cartCount" class="cart-total-pill">{{ money(mix.total) }}</span></h1>
      <button v-if="cartCount" type="button" class="link-btn danger-text" @click="clearCart">{{ $t('cart.clear') }}</button>
    </div>

    <div v-if="!cartCount" class="empty-box">
      <div class="empty-icon"><Icon :icon="ShoppingCart01Icon" :size="40" :stroke-width="1.5" /></div>
      <h3>{{ $t('cart.emptyTitle') }}</h3>
      <p class="muted">{{ $t('cart.emptyText') }}</p>
      <RouterLink to="/catalog" class="btn-primary">{{ $t('cart.checkPrices') }}</RouterLink>
    </div>

    <template v-else>
      <section class="panel">
        <p class="muted small">{{ $t('cart.chooseStores') }}</p>
        <MerchantChips v-model="allowed" multiple />
      </section>

      <div class="tabs" role="tablist">
        <button type="button" role="tab" :aria-selected="mode === 'mix'" :class="{ on: mode === 'mix' }" @click="mode = 'mix'">
          <Icon :icon="FlashIcon" :size="18" /> {{ $t('cart.optimalMix') }}
        </button>
        <button type="button" role="tab" :aria-selected="mode === 'single'" :class="{ on: mode === 'single' }" @click="mode = 'single'">
          <Icon :icon="Store01Icon" :size="18" /> {{ $t('cart.oneStore') }}
        </button>
      </div>

      <!-- ---------- Optimal mix ---------- -->
      <template v-if="mode === 'mix'">
        <section class="summary">
          <h2><Icon :icon="FlashIcon" :size="20" class="title-icon" /> {{ $t('cart.optimalMixTotal', { total: money(mix.total) }) }}</h2>
          <p class="muted small">{{ $t('cart.mixHint') }}</p>
          <p v-if="savings && savings.amount > 0" class="savings">
            <Icon :icon="ArrowDownRight01Icon" :size="16" /> {{ $t('cart.youSave', { amount: money(savings.amount), store: storeName(savings.merchant) }) }}
          </p>
        </section>

        <section v-for="group in mix.groups" :key="group.merchant" class="store-group">
          <header class="store-group-head">
            <MerchantLogo :name="group.merchant" :size="26" />
            <strong>{{ storeName(group.merchant) }}</strong>
            <span class="muted small">{{ $t('cart.items', group.items.length) }}</span>
            <span class="store-subtotal">{{ money(group.subtotal) }}</span>
          </header>

          <div v-for="item in group.items" :key="item.product.id" class="cart-item">
            <span class="cart-emoji" aria-hidden="true">{{ item.product.emoji }}</span>
            <div class="cart-item-body">
              <div class="cart-item-top">
                <RouterLink :to="{ name: 'product', params: { id: item.product.id } }" class="cart-item-name">{{ productName(item.product) }}</RouterLink>
                <button type="button" class="icon-btn" :aria-label="$t('cart.removeItem')" @click="setQty(item.product.id, 0)"><Icon :icon="Delete02Icon" :size="18" /></button>
              </div>
              <div class="cart-item-bottom">
                <QtyStepper :model-value="item.qty" @update:model-value="setQty(item.product.id, $event)" />
                <div class="price-pills">
                  <span
                    v-for="offer in sortedOffers(item.product, allowed)"
                    :key="offer.merchant"
                    class="price-pill"
                    :class="{ chosen: offer.merchant === item.offer.merchant, out: offer.inStock === false }"
                  >
                    <MerchantLogo :name="offer.merchant" :size="16" />
                    {{ offer.inStock === false ? $t('cart.na') : money(offer.price * item.qty) }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section v-if="mix.unavailable.length" class="store-group">
          <header class="store-group-head"><strong>{{ $t('cart.notAvailableAtStores') }}</strong></header>
          <div v-for="line in mix.unavailable" :key="line.product.id" class="cart-item muted">
            <span class="cart-emoji" aria-hidden="true">{{ line.product.emoji }}</span>
            <div class="cart-item-body">
              <div class="cart-item-top">
                <span class="cart-item-name">{{ productName(line.product) }}</span>
                <button type="button" class="icon-btn" :aria-label="$t('cart.removeItem')" @click="setQty(line.product.id, 0)"><Icon :icon="Delete02Icon" :size="18" /></button>
              </div>
            </div>
          </div>
        </section>
      </template>

      <!-- ---------- One store ---------- -->
      <template v-else>
        <section class="summary">
          <h2><Icon :icon="Store01Icon" :size="20" class="title-icon" /> {{ $t('cart.compareByStore') }}</h2>
          <p class="muted small">{{ $t('cart.compareHint') }}</p>
        </section>

        <section v-for="store in stores" :key="store.merchant" class="store-group">
          <header class="store-group-head">
            <MerchantLogo :name="store.merchant" :size="26" />
            <div class="store-meta">
              <strong>{{ storeName(store.merchant) }}</strong>
              <span class="muted small">
                {{ $t('cart.availableOf', { available: store.available, total: cartLines.length }) }}<template v-if="store.missing"> · {{ $t('cart.unavailableCount', { n: store.missing }) }}</template>
              </span>
            </div>
            <div class="store-right">
              <span class="store-subtotal">{{ money(store.total) }}</span>
              <span v-if="!store.missing && store.total > mix.total" class="diff">{{ $t('cart.vsMix', { amount: money(store.total - mix.total) }) }}</span>
              <span v-else-if="!store.missing" class="diff good">{{ $t('cart.bestPrice') }}</span>
            </div>
          </header>
          <button type="button" class="link-btn" @click="openStore = openStore === store.merchant ? null : store.merchant">
            <Icon :icon="openStore === store.merchant ? ArrowUp01Icon : ArrowDown01Icon" :size="16" />
            {{ openStore === store.merchant ? $t('cart.hideItems') : $t('cart.showItems') }}
          </button>
          <ul v-if="openStore === store.merchant" class="store-items">
            <li v-for="item in store.items" :key="item.product.id" :class="{ muted: !item.offer }">
              <span>{{ item.product.emoji }} {{ productName(item.product) }} × {{ item.qty }}</span>
              <span>{{ item.offer ? money(item.lineTotal) : $t('cart.unavailable') }}</span>
            </li>
          </ul>
        </section>
      </template>

      <!-- ---------- Checkout (automated later) ---------- -->
      <section class="checkout-bar">
        <div>
          <span class="muted small">{{ $t('cart.total', cartCount) }}</span>
          <strong class="checkout-total">{{ money(mix.total) }}</strong>
        </div>
        <button type="button" class="btn-primary" disabled :title="$t('cart.comingSoon')">
          <Icon :icon="AiMagicIcon" :size="18" /> {{ $t('cart.checkoutAgent') }} <span class="soon">{{ $t('cart.soon') }}</span>
        </button>
      </section>
    </template>
  </main>
</template>
