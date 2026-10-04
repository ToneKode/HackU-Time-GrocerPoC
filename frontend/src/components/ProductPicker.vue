<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { PERSISTANCE_URL } from '../lib/api.js'
import { money } from '../lib/format.js'
const props = defineProps({ modelValue: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue', 'select'])
const query = ref('')
const rows = ref([])
const loading = ref(false)
const error = ref('')
const selected = ref(null)
let timer, revision = 0
watch(query, () => {
  clearTimeout(timer)
  const current = ++revision
  rows.value = []; error.value = ''; loading.value = false
  if (!query.value.trim()) return
  timer = setTimeout(async () => {
    loading.value = true
    try {
      const response = await fetch(`${PERSISTANCE_URL}/catalog/products?q=${encodeURIComponent(query.value.trim())}&limit=20`)
      if (!response.ok) throw new Error('Product search is unavailable. Please retry.')
      const body = await response.json()
      if (current === revision) rows.value = body
    } catch (err) { if (current === revision) error.value = err.message }
    finally { if (current === revision) loading.value = false }
  }, 250)
})
watch(() => props.modelValue, async (sku) => {
  if (!sku) { selected.value = null; return }
  if (selected.value?.id === sku) return
  try {
    const response = await fetch(`${PERSISTANCE_URL}/catalog/products/${encodeURIComponent(sku)}`)
    if (response.ok && props.modelValue === sku) selected.value = await response.json()
  } catch { /* Search remains available if a saved selection cannot load. */ }
}, { immediate: true })
function choose(row) {
  selected.value = row
  query.value = ''
  emit('update:modelValue', row.id)
  emit('select', row)
}
onBeforeUnmount(() => { clearTimeout(timer); revision++ })
</script>

<template>
  <div class="product-picker" data-testid="product-picker">
    <label class="field"><span>Find product by name</span><input v-model="query" type="search" placeholder="Search baby oil, rice, snacks…" autocomplete="off" /></label>
    <p v-if="selected" class="small" data-testid="selected-product"><strong>{{ selected.name }}</strong> · {{ selected.merchant }} · {{ money(selected.price) }} <span class="muted">({{ selected.id }})</span></p>
    <p v-if="loading" class="muted" role="status">Searching products…</p>
    <p v-else-if="error" role="alert">{{ error }}</p>
    <ul v-else-if="rows.length" class="picker-results">
      <li v-for="row in rows" :key="row.id"><button type="button" @click="choose(row)"><strong>{{ row.name }}</strong><span>{{ row.merchant }} · {{ money(row.price) }} · {{ row.id }}</span></button></li>
    </ul>
    <p v-else-if="query.trim()" class="muted" role="status">No products found. Try another name.</p>
  </div>
</template>

<style scoped>
.picker-results { list-style: none; padding: 0; margin: 0; max-height: 300px; overflow: auto; }
.picker-results button { width: 100%; text-align: left; padding: 12px; border: 1px solid var(--line); background: transparent; cursor: pointer; display: grid; gap: 4px; overflow-wrap: anywhere; }
.picker-results span { font-size: 0.8rem; color: var(--muted); }
.product-picker { min-width: 0; }
</style>
