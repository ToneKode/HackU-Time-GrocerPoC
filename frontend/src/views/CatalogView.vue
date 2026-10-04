<script setup>
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { products, categories, categoryById } from '../data/catalog.js'
import { shelfState } from '../data/loadShelf.js'
import { bestOffer, discountPct } from '../lib/pricing.js'
import ProductCard from '../components/shop/ProductCard.vue'
import MerchantChips from '../components/shop/MerchantChips.vue'
import Icon from '../components/shop/Icon.vue'
import { useI18n } from 'vue-i18n'
import { productName, categoryLabel } from '../i18n/index.js'
import { ShoppingBag01Icon, SearchRemoveIcon } from '@hugeicons/core-free-icons'

const route = useRoute()
const { t } = useI18n()
const router = useRouter()

const merchant = ref(null)
const sort = ref('popular')

const category = computed(() => route.query.category ?? null)
const q = computed(() => (route.query.q ?? '').toString().trim().toLowerCase())

const countByCategory = computed(() => Object.fromEntries(
  categories.map((c) => [c.id, products.filter((p) => p.category === c.id).length]),
))
const shown = ref(48)
watch([category, q, merchant, sort], () => { shown.value = 48 })

function setCategory(id) {
  router.replace({ query: { ...route.query, category: id ?? undefined } })
}

function clearSearch() {
  router.replace({ query: { ...route.query, q: undefined } })
}

const results = computed(() => {
  const allowed = merchant.value ? [merchant.value] : null
  const list = products.filter(
    (p) =>
      (!category.value || p.category === category.value) &&
      (!q.value || p.name.toLowerCase().includes(q.value) || productName(p).toLowerCase().includes(q.value)) &&
      bestOffer(p, allowed),
  )
  const price = (p) => bestOffer(p, allowed).price
  if (sort.value === 'cheap') list.sort((a, b) => price(a) - price(b))
  if (sort.value === 'expensive') list.sort((a, b) => price(b) - price(a))
  if (sort.value === 'discount') list.sort((a, b) => discountPct(bestOffer(b, allowed)) - discountPct(bestOffer(a, allowed)))
  return list
})

const visible = computed(() => results.value.slice(0, shown.value))

const title = computed(() => (categoryById[category.value] ? categoryLabel(category.value) : t('catalog.allProducts')))
</script>

<template>
  <main class="page catalog">
    <aside class="sidebar">
      <h2 class="sidebar-title">{{ $t('catalog.categories') }}</h2>
      <button type="button" class="side-item" :class="{ on: !category }" @click="setCategory(null)">
        <span class="side-label"><Icon :icon="ShoppingBag01Icon" :size="18" /> {{ $t('catalog.allProducts') }}</span><span class="muted">{{ products.length }}</span>
      </button>
      <button
        v-for="c in categories"
        :key="c.id"
        type="button"
        class="side-item"
        :class="{ on: category === c.id }"
        @click="setCategory(c.id)"
      >
        <span class="side-label"><Icon :icon="c.icon" :size="18" /> {{ categoryLabel(c.id) }}</span><span class="muted">{{ countByCategory[c.id] }}</span>
      </button>
    </aside>

    <section class="catalog-main">
      <MerchantChips v-model="merchant" />

      <div class="section-head">
        <h2>{{ title }} <span class="muted">({{ results.length }})</span></h2>
        <p v-if="shelfState.source === 'database'" class="muted shelf-note">{{ $t('catalog.fromDatabase', { n: shelfState.count }) }}</p>
        <select v-model="sort" class="sort" :aria-label="$t('catalog.sortLabel')">
          <option value="popular">{{ $t('catalog.popular') }}</option>
          <option value="cheap">{{ $t('catalog.cheap') }}</option>
          <option value="expensive">{{ $t('catalog.expensive') }}</option>
          <option value="discount">{{ $t('catalog.discount') }}</option>
        </select>
      </div>

      <p v-if="q" class="search-note">
        {{ $t('catalog.resultsFor', { q: route.query.q }) }}
        <button type="button" class="link-btn" @click="clearSearch">{{ $t('catalog.clear') }}</button>
      </p>

      <div class="product-grid">
        <ProductCard v-for="p in visible" :key="p.id" :product="p" :merchant="merchant" />
      </div>
      <div v-if="results.length > visible.length" class="catalog-more">
        <button type="button" class="btn-soft" @click="shown += 48">
          {{ $t('catalog.showMore') }} ({{ visible.length }} / {{ results.length }})
        </button>
      </div>

      <div v-if="!results.length" class="empty-box">
        <div class="empty-icon"><Icon :icon="SearchRemoveIcon" :size="40" :stroke-width="1.5" /></div>
        <h3>{{ $t('catalog.nothingFound') }}</h3>
        <p class="muted">{{ $t('catalog.nothingFoundHint') }}</p>
      </div>
    </section>
  </main>
</template>
