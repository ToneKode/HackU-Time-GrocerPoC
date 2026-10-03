<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { productById } from '../data/catalog.js'
import { bestOffer, discountPct } from '../lib/pricing.js'
import { productHistory } from '../lib/priceHistory.js'
import { money } from '../lib/format.js'
import { favourites, favouriteCount, clearFavourites, qtyOf, setQty } from '../stores/shop.js'
import { productName, storeName } from '../i18n/index.js'
import ProductCard from '../components/shop/ProductCard.vue'
import MerchantChips from '../components/shop/MerchantChips.vue'
import Icon from '../components/shop/Icon.vue'
import {
  FavouriteIcon, ShoppingCartAdd01Icon, Delete02Icon, CheckmarkCircle02Icon, ArrowRight01Icon,
} from '@hugeicons/core-free-icons'

const { t } = useI18n()

// Products stay on the page after you un-heart them (so a mis-tap is easy to undo);
// they're gone the next time you open the page.
const shownIds = ref(Object.keys(favourites.ids))
watch(
  () => Object.keys(favourites.ids),
  (ids) => {
    for (const id of ids) if (!shownIds.value.includes(id)) shownIds.value.push(id)
  },
)

const merchant = ref(null)
const sort = ref('recent')
const savedAt = (id) => (typeof favourites.ids[id] === 'number' ? favourites.ids[id] : 0)

const products = computed(() => {
  const allowed = merchant.value ? [merchant.value] : null
  const list = shownIds.value.map((id) => productById[id]).filter((p) => p && (!allowed || bestOffer(p, allowed)))
  const price = (p) => bestOffer(p, allowed)?.price ?? Infinity
  if (sort.value === 'recent') list.sort((a, b) => savedAt(b.id) - savedAt(a.id))
  if (sort.value === 'cheap') list.sort((a, b) => price(a) - price(b))
  if (sort.value === 'discount') list.sort((a, b) => discountPct(bestOffer(b, allowed)) - discountPct(bestOffer(a, allowed)))
  return list
})

// Favourites whose best price today is at (or within 2% of) its 30-day low.
// Uses shownIds too, so un-hearting doesn't make the page jump.
const goodTime = computed(() =>
  shownIds.value
    .map((id) => productById[id])
    .filter((p) => p && bestOffer(p))
    .map((p) => ({ product: p, best: bestOffer(p), stats: productHistory(p, 30).stats }))
    .filter((x) => x.stats.current <= x.stats.low * 1.02),
)

// ---- Bulk actions ----
const note = ref('')
let noteTimer
function flash(text) {
  note.value = text
  clearTimeout(noteTimer)
  noteTimer = setTimeout(() => (note.value = ''), 3000)
}

function addAllToCart() {
  let added = 0
  for (const id of Object.keys(favourites.ids)) {
    const p = productById[id]
    if (p && bestOffer(p) && !qtyOf(id)) {
      setQty(id, 1)
      added++
    }
  }
  flash(added ? t('fav.addedToCart', added) : t('fav.alreadyInCart'))
}

function clearAll() {
  if (!window.confirm(t('fav.confirmClear'))) return
  clearFavourites()
  shownIds.value = []
}
</script>

<template>
  <main class="page">
    <div class="cart-head">
      <h1 class="fav-title">
        <Icon :icon="FavouriteIcon" :size="26" class="fav-title-icon" />
        {{ $t('fav.title') }} <span class="muted">({{ favouriteCount }})</span>
      </h1>
      <button v-if="favouriteCount" type="button" class="link-btn danger-text" @click="clearAll">
        <Icon :icon="Delete02Icon" :size="16" /> {{ $t('fav.clearAll') }}
      </button>
    </div>

    <div v-if="!shownIds.length" class="empty-box">
      <div class="empty-icon"><Icon :icon="FavouriteIcon" :size="40" :stroke-width="1.5" /></div>
      <h3>{{ $t('fav.emptyTitle') }}</h3>
      <p class="muted">{{ $t('fav.emptyText') }}</p>
      <RouterLink to="/catalog" class="btn-primary">{{ $t('home.browseCatalog') }}</RouterLink>
    </div>

    <template v-else>
      <!-- Good time to buy -->
      <section v-if="goodTime.length" class="pd-card fav-deals">
        <h2 class="pd-h2 fav-deals-title">
          <Icon :icon="CheckmarkCircle02Icon" :size="20" /> {{ $t('fav.goodTime') }}
        </h2>
        <p class="muted small">{{ $t('fav.goodTimeHint') }}</p>
        <ul class="fav-deal-list">
          <li v-for="x in goodTime" :key="x.product.id">
            <span class="cart-emoji fav-deal-emoji" aria-hidden="true">{{ x.product.emoji }}</span>
            <RouterLink :to="{ name: 'product', params: { id: x.product.id } }" class="fav-deal-name">
              {{ productName(x.product) }}
              <span class="muted small">{{ storeName(x.best.merchant) }}</span>
            </RouterLink>
            <strong class="price fav-deal-price">{{ money(x.best.price) }}</strong>
            <Icon :icon="ArrowRight01Icon" :size="16" class="muted" />
          </li>
        </ul>
      </section>

      <!-- Toolbar -->
      <MerchantChips v-model="merchant" />
      <div class="section-head fav-toolbar">
        <select v-model="sort" class="sort" :aria-label="$t('catalog.sortLabel')">
          <option value="recent">{{ $t('fav.sortRecent') }}</option>
          <option value="cheap">{{ $t('catalog.cheap') }}</option>
          <option value="discount">{{ $t('catalog.discount') }}</option>
        </select>
        <div class="fav-actions">
          <span v-if="note" class="fav-note" role="status">
            {{ note }} <RouterLink to="/cart" class="link-btn">{{ $t('nav.cart') }} →</RouterLink>
          </span>
          <button type="button" class="btn-soft" :disabled="!favouriteCount" @click="addAllToCart">
            <Icon :icon="ShoppingCartAdd01Icon" :size="18" /> {{ $t('fav.addAll') }}
          </button>
        </div>
      </div>

      <div class="product-grid">
        <ProductCard v-for="p in products" :key="p.id" :product="p" :merchant="merchant" />
      </div>
      <p v-if="!products.length" class="empty-note">{{ $t('fav.noneAtStore') }}</p>
    </template>
  </main>
</template>
