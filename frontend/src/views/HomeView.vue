<script setup>
import { ref, computed } from 'vue'
import { products, categories, merchants } from '../data/catalog.js'
import { bestOffer, discountPct } from '../lib/pricing.js'
import ProductCard from '../components/shop/ProductCard.vue'
import MerchantChips from '../components/shop/MerchantChips.vue'
import Icon from '../components/shop/Icon.vue'
import { storeName, categoryLabel, listOf } from '../i18n/index.js'
import {
  BroccoliIcon, MilkBottleIcon, Bread01Icon, Apple01Icon, TissuePaperIcon, EggsIcon, FlashIcon,
} from '@hugeicons/core-free-icons'

const heroIcons = [
  { icon: BroccoliIcon, color: '#2f9e44' },
  { icon: MilkBottleIcon, color: '#3d6ef0' },
  { icon: Bread01Icon, color: '#c47f17' },
  { icon: Apple01Icon, color: '#e03131' },
  { icon: TissuePaperIcon, color: '#7048e8' },
  { icon: EggsIcon, color: '#d9480f' },
]

const merchant = ref(null)

// Deals = products whose best price (for the chosen store) is discounted, biggest first.
const deals = computed(() => {
  const allowed = merchant.value ? [merchant.value] : null
  return products
    .map((product) => ({ product, pct: discountPct(bestOffer(product, allowed)) }))
    .filter((d) => d.pct > 0)
    .sort((a, b) => b.pct - a.pct)
    .map((d) => d.product)
})

const spotlight = computed(() => {
  if (deals.value.length) return deals.value
  const allowed = merchant.value ? [merchant.value] : null
  return products.filter((product) => bestOffer(product, allowed)).slice(0, 8)
})
</script>

<template>
  <main class="page">
    <section class="hero">
      <div class="hero-text">
        <h1>{{ $t('home.heroTitle') }} <span class="accent">{{ $t('home.heroAccent') }}</span></h1>
        <p>{{ $t('home.heroText', { stores: listOf(merchants.map((m) => storeName(m.name))) }) }}</p>
        <div class="hero-actions">
          <RouterLink to="/catalog" class="btn-primary">{{ $t('home.browseCatalog') }}</RouterLink>
          <RouterLink to="/cart" class="btn-soft">{{ $t('home.openCart') }}</RouterLink>
        </div>
      </div>
      <div class="hero-art" aria-hidden="true">
        <span v-for="(h, i) in heroIcons" :key="i" :style="{ color: h.color }"><Icon :icon="h.icon" :size="48" :stroke-width="1.5" /></span>
      </div>
    </section>

    <nav class="category-row" :aria-label="$t('home.categories')">
      <RouterLink
        v-for="c in categories"
        :key="c.id"
        :to="{ name: 'catalog', query: { category: c.id } }"
        class="category-pill"
        :style="{ background: c.tint }"
      >
        <Icon :icon="c.icon" :size="20" class="category-icon" />{{ categoryLabel(c.id) }}
      </RouterLink>
    </nav>

    <section>
      <div class="section-head">
        <h2><Icon :icon="FlashIcon" :size="22" class="title-icon" /> {{ deals.length ? $t('home.megaDeals') : $t('catalog.allProducts') }} <span class="muted">({{ spotlight.length }})</span></h2>
      </div>
      <MerchantChips v-model="merchant" />
      <div class="product-grid">
        <ProductCard v-for="p in spotlight" :key="p.id" :product="p" :merchant="merchant" />
      </div>
      <p v-if="!spotlight.length" class="empty-note">{{ $t('home.noDeals') }}</p>
    </section>
  </main>
</template>
