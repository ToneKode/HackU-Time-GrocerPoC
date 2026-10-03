<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { productById, products, categoryById, merchantByName } from '../data/catalog.js'
import { sortedOffers, bestOffer, discountPct } from '../lib/pricing.js'
import { productHistory, daysSinceChange, PERIODS } from '../lib/priceHistory.js'
import { money } from '../lib/format.js'
import { qtyOf, setQty, addToCart, favourites, toggleFavourite } from '../stores/shop.js'
import ProductCard from '../components/shop/ProductCard.vue'
import MerchantLogo from '../components/shop/MerchantLogo.vue'
import QtyStepper from '../components/shop/QtyStepper.vue'
import PriceChart from '../components/shop/PriceChart.vue'
import Icon from '../components/shop/Icon.vue'
import { useI18n } from 'vue-i18n'
import { productName, productSize, storeName, categoryLabel, dateLocale } from '../i18n/index.js'
import {
  ArrowLeft01Icon, Share08Icon, FavouriteIcon, PlusSignIcon, ArrowDown01Icon, ArrowUp01Icon,
  CheckmarkCircle02Icon, AlertCircleIcon, InformationCircleIcon, ChartLineData02Icon, Table01Icon,
} from '@hugeicons/core-free-icons'

const route = useRoute()
const { t } = useI18n()
const router = useRouter()

const product = computed(() => productById[route.params.id])
const category = computed(() => categoryById[product.value?.category])
const offers = computed(() => sortedOffers(product.value))
const best = computed(() => bestOffer(product.value))
const discount = computed(() => discountPct(best.value))
const qty = computed({
  get: () => qtyOf(product.value.id),
  set: (value) => setQty(product.value.id, value),
})

// ---- Store list ----
const openStore = ref(null)
function toggleStore(name) {
  openStore.value = openStore.value === name ? null : name
}

// ---- Price history ----
const days = ref(30)
const mode = ref('min') // 'min' | 'stores'
const showTable = ref(false)
const history = computed(() => productHistory(product.value, days.value))
const stats = computed(() => history.value.stats)
const fmtDate = (ts) => new Date(ts).toLocaleDateString(dateLocale(), { day: 'numeric', month: 'short' })

const chartSeries = computed(() =>
  mode.value === 'min'
    ? [{ key: 'min', label: t('product.lowestPrice'), color: 'var(--primary)', points: history.value.minPoints }]
    : history.value.stores.map((s) => ({ key: s.merchant, label: storeName(s.merchant), color: merchantByName[s.merchant].color, points: s.points })),
)

// Verdict on today's price, with an icon + label (never colour alone).
const verdict = computed(() => {
  const s = stats.value
  if (s.current <= s.low * 1.02) return { tone: 'good', icon: CheckmarkCircle02Icon, text: t('product.verdictGood', { days: days.value }) }
  if (s.current > s.avg * 1.02) return { tone: 'warn', icon: AlertCircleIcon, text: t('product.verdictWarn', { days: days.value }) }
  return { tone: 'neutral', icon: InformationCircleIcon, text: t('product.verdictNeutral', { days: days.value }) }
})

const pct = (n) => (n > 0 ? `+${n}%` : `${n}%`)

// ---- Similar products ----
const similar = computed(() =>
  products.filter((p) => p.category === product.value.category && p.id !== product.value.id).slice(0, 8),
)

// ---- Header actions ----
const shareNote = ref('')
async function share() {
  const url = window.location.href
  try {
    if (navigator.share) await navigator.share({ title: productName(product.value), url })
    else {
      await navigator.clipboard.writeText(url)
      shareNote.value = t('product.linkCopied')
      setTimeout(() => (shareNote.value = ''), 2000)
    }
  } catch {
    // Share sheet closed or clipboard blocked: nothing to do.
  }
}
function goBack() {
  if (window.history.state?.back) router.back()
  else router.push('/')
}
</script>

<template>
  <main v-if="product" class="page product-page">
    <div class="top-actions">
      <button type="button" class="link-btn plain" @click="goBack">
        <Icon :icon="ArrowLeft01Icon" :size="18" /> {{ $t('product.back') }}
      </button>
      <button type="button" class="link-btn plain" @click="share">
        <Icon :icon="Share08Icon" :size="18" /> {{ shareNote || $t('product.share') }}
      </button>
    </div>

    <!-- ---------- Main card ---------- -->
    <section class="pd-main">
      <div class="product-image pd-image" :style="{ background: category?.tint }">
        <span v-if="discount" class="discount">-{{ discount }}%</span>
        <button
          type="button"
          class="fav"
          :class="{ on: favourites.ids[product.id] }"
          :aria-label="favourites.ids[product.id] ? $t('card.removeFavourite') : $t('card.addFavourite')"
          @click="toggleFavourite(product.id)"
        >
          <Icon :icon="FavouriteIcon" :size="18" />
        </button>
        <span class="product-emoji pd-emoji" aria-hidden="true">{{ product.emoji }}</span>
        <span class="size">{{ productSize(product) }}</span>
      </div>

      <div class="pd-info">
        <RouterLink v-if="category" :to="{ name: 'catalog', query: { category: category.id } }" class="pd-crumb">
          <Icon :icon="category.icon" :size="16" /> {{ categoryLabel(category.id) }}
        </RouterLink>
        <h1 class="pd-title">{{ productName(product) }}</h1>
        <p v-if="best" class="muted small">
          {{ $t('product.cheapestAt', { store: storeName(best.merchant) }) }} · {{ $t('product.inStockCount', stats.storeCount) }}
        </p>

        <div class="pd-price">
          <template v-if="best">
            <s v-if="best.oldPrice" class="old-price">{{ money(best.oldPrice) }}</s>
            <span class="price pd-price-big">{{ money(best.price) }}</span>
          </template>
          <span v-else class="muted">{{ $t('product.notAvailableNow') }}</span>
        </div>

        <QtyStepper v-if="qty" v-model="qty" class="pd-action" />
        <button v-else type="button" class="add-btn pd-action" :disabled="!best" @click="addToCart(product.id)">
          <Icon :icon="PlusSignIcon" :size="16" :stroke-width="2.2" /> {{ $t('card.addToCart') }}
        </button>
      </div>
    </section>

    <!-- ---------- Prices by store ---------- -->
    <section class="pd-card">
      <h2 class="pd-h2">{{ $t('product.pricesByStore') }}</h2>
      <ul class="store-rows">
        <li v-for="offer in offers" :key="offer.merchant" :class="{ out: offer.inStock === false }">
          <button
            type="button"
            class="store-row"
            :aria-expanded="openStore === offer.merchant"
            @click="toggleStore(offer.merchant)"
          >
            <MerchantLogo :name="offer.merchant" :size="26" />
            <span class="store-row-name">{{ storeName(offer.merchant) }}</span>
            <span v-if="offer.inStock === false" class="out-tag">{{ $t('card.outOfStock') }}</span>
            <span v-else-if="best && offer.merchant === best.merchant" class="best-tag">{{ $t('product.bestPrice') }}</span>
            <span class="store-row-price">
              <s v-if="offer.oldPrice" class="old-price">{{ money(offer.oldPrice) }}</s>
              {{ money(offer.price) }}
            </span>
            <Icon :icon="openStore === offer.merchant ? ArrowUp01Icon : ArrowDown01Icon" :size="16" class="muted" />
          </button>
          <dl v-if="openStore === offer.merchant" class="store-detail">
            <div>
              <dt>{{ $t('product.discount') }}</dt>
              <dd>{{ discountPct(offer) ? $t('product.discountValue', { pct: discountPct(offer), old: money(offer.oldPrice) }) : $t('product.none') }}</dd>
            </div>
            <div>
              <dt>{{ $t('product.vsCheapest') }}</dt>
              <dd>{{ best && offer.price > best.price ? '+' + money(offer.price - best.price) : $t('product.cheapest') }}</dd>
            </div>
            <div>
              <dt>{{ $t('product.unchangedFor') }}</dt>
              <dd>{{ $t('product.days', daysSinceChange(product, offer)) }}</dd>
            </div>
            <div>
              <dt>{{ $t('product.lowHere', { days }) }}</dt>
              <dd>{{ money(history.stores.find((s) => s.merchant === offer.merchant).low) }}</dd>
            </div>
          </dl>
        </li>
      </ul>
    </section>

    <!-- ---------- Price stats + history ---------- -->
    <section class="pd-card">
      <div class="pd-history-head">
        <div>
          <h2 class="pd-h2">{{ $t('product.priceHistory') }}</h2>
          <p class="muted small">{{ fmtDate(history.start) }} – {{ fmtDate(history.end) }}</p>
        </div>
        <div class="segmented" role="group" :aria-label="$t('product.period')">
          <button
            v-for="d in PERIODS"
            :key="d"
            type="button"
            :class="{ on: days === d }"
            :aria-pressed="days === d"
            @click="days = d"
          >{{ $t('product.periodOption', { n: d }) }}</button>
        </div>
      </div>

      <div class="stat-tiles">
        <div class="stat-tile">
          <span class="stat-label">{{ $t('product.todaysBest') }}</span>
          <strong class="stat-value">{{ money(stats.current) }}</strong>
          <span class="stat-sub">{{ $t('product.vsAverage', { pct: pct(stats.vsAvgPct) }) }}</span>
        </div>
        <div class="stat-tile">
          <span class="stat-label">{{ $t('product.periodLow', { days }) }}</span>
          <strong class="stat-value">{{ money(stats.low) }}</strong>
        </div>
        <div class="stat-tile">
          <span class="stat-label">{{ $t('product.periodHigh', { days }) }}</span>
          <strong class="stat-value">{{ money(stats.high) }}</strong>
        </div>
        <div class="stat-tile">
          <span class="stat-label">{{ $t('product.average') }}</span>
          <strong class="stat-value">{{ money(stats.avg) }}</strong>
        </div>
        <div class="stat-tile">
          <span class="stat-label">{{ $t('product.storeGap') }}</span>
          <strong class="stat-value">{{ money(stats.spread) }}</strong>
          <span class="stat-sub">{{ $t('product.storeGapSub') }}</span>
        </div>
      </div>

      <p class="verdict" :class="`verdict-${verdict.tone}`">
        <Icon :icon="verdict.icon" :size="18" /> {{ verdict.text }}
      </p>

      <div class="pd-chart-controls">
        <div class="segmented" role="group" :aria-label="$t('product.chartMode')">
          <button type="button" :class="{ on: mode === 'min' }" :aria-pressed="mode === 'min'" @click="mode = 'min'">{{ $t('product.lowestPrice') }}</button>
          <button type="button" :class="{ on: mode === 'stores' }" :aria-pressed="mode === 'stores'" @click="mode = 'stores'">{{ $t('product.byStore') }}</button>
        </div>
        <button type="button" class="link-btn" @click="showTable = !showTable">
          <Icon :icon="showTable ? ChartLineData02Icon : Table01Icon" :size="16" />
          {{ showTable ? $t('product.showChart') : $t('product.showTable') }}
        </button>
      </div>

      <template v-if="!showTable">
        <PriceChart :series="chartSeries" :annotate="mode === 'min'" />
        <ul v-if="mode === 'stores'" class="chart-legend">
          <li v-for="s in history.stores" :key="s.merchant">
            <span class="legend-key" :style="{ background: merchantByName[s.merchant].color }" />
            {{ storeName(s.merchant) }}
            <strong>{{ money(s.current) }}</strong>
            <span :class="s.changePct < 0 ? 'down' : s.changePct > 0 ? 'up' : 'muted'">{{ pct(s.changePct) }}</span>
          </li>
        </ul>
      </template>

      <div v-else class="table-scroll">
        <table class="price-table">
          <thead>
            <tr>
              <th>{{ $t('product.colStore') }}</th><th>{{ $t('product.colToday') }}</th><th>{{ $t('product.colLow') }}</th>
              <th>{{ $t('product.colHigh') }}</th><th>{{ $t('product.colAverage') }}</th><th>{{ $t('product.colChange') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in history.stores" :key="s.merchant">
              <td><span class="legend-key" :style="{ background: merchantByName[s.merchant].color }" /> {{ storeName(s.merchant) }}</td>
              <td>{{ money(s.current) }}</td>
              <td>{{ money(s.low) }}</td>
              <td>{{ money(s.high) }}</td>
              <td>{{ money(s.avg) }}</td>
              <td>{{ pct(s.changePct) }}</td>
            </tr>
            <tr class="table-total">
              <td>{{ $t('product.lowestAcross') }}</td>
              <td>{{ money(stats.current) }}</td>
              <td>{{ money(stats.low) }}</td>
              <td>{{ money(stats.high) }}</td>
              <td>{{ money(stats.avg) }}</td>
              <td>{{ pct(stats.changePct) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ---------- Similar products ---------- -->
    <section v-if="similar.length">
      <div class="section-head">
        <h2>{{ $t('product.similar') }}</h2>
        <span class="muted small">{{ $t('cart.items', similar.length) }}</span>
      </div>
      <div class="product-grid">
        <ProductCard v-for="p in similar" :key="p.id" :product="p" />
      </div>
    </section>
  </main>

  <main v-else class="page">
    <div class="empty-box">
      <h3>{{ $t('product.notFound') }}</h3>
      <RouterLink to="/catalog" class="btn-primary">{{ $t('product.backToCatalog') }}</RouterLink>
    </div>
  </main>
</template>
