<script setup>
// "Add a product" / "Alternatives" popup over the basket review sheet.
// Lists every product the agent can buy (GET /agent/products) with search, filters and sorting.
import { ref, computed, watch, nextTick } from 'vue'
import * as api from '../lib/api.js'
import { money } from '../lib/format.js'
import { categoryArt, categoryKey } from '../lib/productArt.js'
import { storeName } from '../i18n/index.js'
import MerchantLogo from './shop/MerchantLogo.vue'
import Icon from './shop/Icon.vue'
import { Cancel01Icon, Search01Icon, PlusSignIcon, ArrowDataTransferHorizontalIcon, SearchRemoveIcon } from '@hugeicons/core-free-icons'

const props = defineProps({
  open: Boolean,
  replacing: { type: Object, default: null }, // basket item being swapped, or null to add
  inBasket: { type: Object, default: () => ({}) }, // sku -> qty
})
const emit = defineEmits(['pick', 'close'])

// ---- Data (loaded once) ----
const products = ref([])
const loading = ref(false)
const error = ref('')
async function load() {
  if (products.value.length || loading.value) return
  loading.value = true
  error.value = ''
  try {
    products.value = await api.listProducts()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

// ---- Filters ----
const query = ref('')
const category = ref('')
const store = ref('')
const sort = ref('cheap')
const searchInput = ref(null)

const categories = computed(() => [...new Set(products.value.map((p) => p.category))].sort())
const stores = computed(() => [...new Set(products.value.map((p) => p.merchant))].sort())

const results = computed(() => {
  const q = query.value.trim().toLowerCase()
  const list = products.value.filter(
    (p) =>
      (!category.value || p.category === category.value) &&
      (!store.value || p.merchant === store.value) &&
      (!q || `${p.name} ${p.merchant} ${p.category}`.toLowerCase().includes(q)),
  )
  if (sort.value === 'cheap') list.sort((a, b) => a.price - b.price)
  if (sort.value === 'expensive') list.sort((a, b) => b.price - a.price)
  if (sort.value === 'name') list.sort((a, b) => a.name.localeCompare(b.name))
  return list
})

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    query.value = ''
    store.value = ''
    category.value = props.replacing?.category ?? ''
    load()
    await nextTick()
    searchInput.value?.focus()
  },
)

function onKey(event) {
  if (event.key === 'Escape') {
    event.stopPropagation()
    emit('close')
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="sheet-fade">
      <div v-if="open" class="picker-backdrop" @click="emit('close')" />
    </Transition>
    <Transition name="picker-pop">
      <section
        v-if="open"
        class="picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby="picker-title"
        @keydown="onKey"
      >
        <header class="picker-head">
          <div>
            <h2 id="picker-title">
              {{ replacing ? $t('picker.alternativesTitle') : $t('picker.addTitle') }}
            </h2>
            <p v-if="replacing" class="muted small picker-sub">{{ $t('picker.replacing', { name: replacing.name }) }}</p>
          </div>
          <button type="button" class="basket-close" :aria-label="$t('basket.close')" @click="emit('close')">
            <Icon :icon="Cancel01Icon" :size="20" />
          </button>
        </header>

        <div class="picker-controls">
          <label class="search picker-search">
            <span class="search-icon"><Icon :icon="Search01Icon" :size="18" /></span>
            <input ref="searchInput" v-model="query" type="search" :placeholder="$t('picker.searchPlaceholder')" :aria-label="$t('picker.searchPlaceholder')" />
          </label>
          <select v-model="store" class="sort" :aria-label="$t('picker.store')">
            <option value="">{{ $t('stores.all') }}</option>
            <option v-for="s in stores" :key="s" :value="s">{{ storeName(s) }}</option>
          </select>
          <select v-model="sort" class="sort" :aria-label="$t('catalog.sortLabel')">
            <option value="cheap">{{ $t('catalog.cheap') }}</option>
            <option value="expensive">{{ $t('catalog.expensive') }}</option>
            <option value="name">{{ $t('picker.sortName') }}</option>
          </select>
        </div>

        <div class="chips-row picker-cats" role="group" :aria-label="$t('picker.category')">
          <button type="button" class="store-chip" :class="{ on: !category }" :aria-pressed="!category" @click="category = ''">
            {{ $t('picker.allCategories') }}
          </button>
          <button
            v-for="c in categories"
            :key="c"
            type="button"
            class="store-chip"
            :class="{ on: category === c }"
            :aria-pressed="category === c"
            @click="category = c"
          >
            <span aria-hidden="true">{{ categoryArt(c).emoji }}</span>
            {{ $te(`productCats.${categoryKey(c)}`) ? $t(`productCats.${categoryKey(c)}`) : c }}
          </button>
        </div>

        <div class="picker-body">
          <p v-if="loading" class="muted picker-state">{{ $t('picker.loading') }}</p>
          <p v-else-if="error" class="error picker-state">{{ $t('agentChat.error', { message: error }) }}</p>
          <div v-else-if="!results.length" class="picker-state">
            <Icon :icon="SearchRemoveIcon" :size="36" :stroke-width="1.5" class="muted" />
            <p class="muted">{{ $t('catalog.nothingFound') }}</p>
          </div>

          <ul v-else class="picker-grid">
            <li v-for="p in results" :key="p.id" class="picker-item" :class="{ current: replacing && replacing.sku === p.id }">
              <div class="basket-img" :style="{ background: categoryArt(p.category).tint }">
                <img v-if="p.image_url" :src="p.image_url" :alt="p.name" loading="lazy" />
                <span v-else class="basket-emoji" aria-hidden="true">{{ categoryArt(p.category).emoji }}</span>
                <span v-if="inBasket[p.id]" class="basket-qty">{{ $t('picker.inBasket', { n: inBasket[p.id] }) }}</span>
              </div>
              <div class="basket-store">
                <MerchantLogo :name="p.merchant" :size="18" />
                <span>{{ storeName(p.merchant) }}</span>
              </div>
              <!-- Product names come from the mall: plain text only. -->
              <h3 class="basket-name">{{ p.name }}</h3>
              <span v-if="p.sell_point && $te(`basket.sellPoint.${p.sell_point}`)" class="basket-badge">
                {{ $t(`basket.sellPoint.${p.sell_point}`) }}
              </span>
              <div class="picker-foot">
                <strong class="picker-price">{{ money(p.price) }}</strong>
                <button
                  type="button"
                  class="btn-soft picker-add"
                  :disabled="replacing && replacing.sku === p.id"
                  @click="emit('pick', p)"
                >
                  <Icon :icon="replacing ? ArrowDataTransferHorizontalIcon : PlusSignIcon" :size="16" :stroke-width="2.2" />
                  {{ replacing ? $t('picker.swap') : inBasket[p.id] ? $t('picker.addMore') : $t('picker.add') }}
                </button>
              </div>
            </li>
          </ul>
        </div>

        <footer class="picker-done">
          <span class="muted small">{{ $t('picker.count', results.length) }}</span>
          <button type="button" class="btn-primary" @click="emit('close')">{{ $t('picker.done') }}</button>
        </footer>
      </section>
    </Transition>
  </Teleport>
</template>
