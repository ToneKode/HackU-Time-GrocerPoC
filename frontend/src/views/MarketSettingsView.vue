<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { session } from '../stores/auth.js'
import { getMarketRules, saveMarketRules, updateCatalogProduct } from '../lib/api.js'
import { loadDatabaseCatalog } from '../data/loadShelf.js'
import { productById } from '../data/catalog.js'
import { money } from '../lib/format.js'
import ProductPicker from '../components/ProductPicker.vue'

const router = useRouter()
const promotions = ref([])
const paymentPromotions = ref([])
const version = ref('')
const busy = ref(false)
const ready = ref(false)
const error = ref('')
const notice = ref('')
const sku = ref('')
const price = ref(0)
const adminPassword = ref('')
const previewAmount = ref(150)
const selected = computed(() => productById[sku.value])
const actor = () => session.user?.role === 'admin' ? session.user.id : null
let revision = 0
watch(() => [session.user?.id, session.user?.role], () => {
  revision++
  adminPassword.value = ''
  ready.value = false
  if (!actor()) router.replace('/')
})
watch(selected, (product) => {
  if (!product) return
  price.value = product.offers[0]?.price ?? 0
})
function addPromotion(merchant = '', threshold = 0, rate = 0, kind = 'percent') {
  promotions.value.push({ id: `promo-${Date.now()}-${promotions.value.length}`, merchant, kind, threshold, rate, sku: '', enabled: true })
}
function addPaymentPromotion(kind = 'cash', rate = 0) {
  paymentPromotions.value.push({ route: 'mastercard', kind, rate, merchant: '', enabled: true })
}
function paymentRateValue(promotion) {
  return promotion.kind === 'cash' ? Number((promotion.rate * 100).toFixed(10)) : promotion.rate
}
function updatePaymentRate(promotion, value) {
  promotion.rate = promotion.kind === 'cash' ? Number(value) / 100 : Number(value)
}
async function run(task) {
  const id = actor()
  if (!id || !adminPassword.value || busy.value) return
  const current = revision
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await task(id, () => revision === current && actor() === id)
  } catch (err) {
    if (revision === current) error.value = err.message
  } finally {
    if (revision === current) busy.value = false
  }
}
function apply(body) {
  version.value = body.version
  promotions.value = (body.promotions || []).map((row) => ({ ...row }))
  paymentPromotions.value = (body.payment_promotions || []).map((row) => ({ ...row }))
  ready.value = true
}
function load() {
  return run(async (id, current) => {
    const body = await getMarketRules(id, adminPassword.value)
    if (current()) apply(body)
  })
}
function save() {
  return run(async (id, current) => {
    const body = await saveMarketRules(id, { version: version.value, promotions: promotions.value, payment_promotions: paymentPromotions.value }, adminPassword.value)
    if (current()) { apply(body); notice.value = 'Market rules saved.' }
  })
}
function saveProduct() {
  return run(async (id, current) => {
    const savedSku = sku.value.trim()
    await updateCatalogProduct(id, savedSku, { price: price.value }, adminPassword.value)
    if (!current()) return
    const refreshed = await loadDatabaseCatalog()
    if (current()) notice.value = refreshed ? 'Product saved. Live catalog refreshed.' : 'Product saved. Catalog refresh unavailable; reload to try again.'
  })
}
</script>

<template>
  <main v-if="session.user?.role === 'admin'" class="market-settings" data-testid="market-settings-page">
    <header><h1>Market settings</h1><p class="muted">Manage store and payment promotions and live product prices.</p></header>
    <p v-if="error" class="sheet-alert" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <section class="card">
      <h2>Admin authentication</h2>
      <form data-testid="admin-password-form" @submit.prevent="load">
        <label class="field"><span>Your account password</span><input v-model="adminPassword" data-testid="admin-password" type="password" autocomplete="off" required :disabled="busy" /></label>
        <p class="muted small">Enter your account password to load and save settings. It is kept only while this page is open.</p>
        <button type="submit" class="btn primary" data-testid="market-load" :disabled="busy || !adminPassword">Load saved rules</button>
      </form>
    </section>
    <section class="card">
      <div class="approval-head"><h2>Promotions</h2><span class="pill" data-testid="market-version">Version {{ version || '—' }}</span></div>
      <form v-if="ready" data-testid="market-rules-form" @submit.prevent="save">
        <fieldset v-for="(promotion, index) in promotions" :key="promotion.id" class="promotion-row" :data-promotion-id="promotion.id" :disabled="busy">
          <legend>{{ promotion.merchant || 'New promotion' }}</legend>
          <label class="field"><span>Merchant</span><input v-model="promotion.merchant" name="merchant" :required="promotion.kind === 'percent'" /></label>
          <label class="field"><span>Type</span><select v-model="promotion.kind" name="kind"><option value="percent">Spend threshold discount</option><option value="bogo">Buy 1 get 1</option></select></label>
          <template v-if="promotion.kind === 'percent'">
            <label class="field"><span>Threshold (HK$)</span><input v-model.number="promotion.threshold" name="threshold" type="number" min="0" step="0.01" required /></label>
            <label class="field"><span>Discount rate (0.10 = 10%)</span><input v-model.number="promotion.rate" name="rate" type="number" min="0" max="1" step="0.01" required /></label>
          </template>
          <ProductPicker v-else v-model="promotion.sku" @select="(product) => { promotion.merchant = product.merchant; promotion.gift_sku = product.id }" />
          <label><input v-model="promotion.enabled" name="enabled" type="checkbox" /> Enabled</label>
          <button type="button" class="link-btn danger-text" @click="promotions.splice(index, 1)">Remove</button>
        </fieldset>
        <section data-testid="payment-promotions">
          <h2>Payment promotions</h2>
          <p class="muted small">Cashback is a percentage of spend. Miles and points are earned per HKD spent. Leave merchant blank to apply to all merchants.</p>
          <fieldset v-for="(promotion, index) in paymentPromotions" :key="index" class="promotion-row" data-testid="payment-promotion-row" :disabled="busy">
            <legend>Payment promotion {{ index + 1 }}</legend>
            <label class="field"><span>Payment route</span><select v-model="promotion.route" data-testid="payment-promotion-route" name="payment-route"><option value="mastercard">Mastercard</option><option value="visa">Visa</option><option value="alipay">Alipay</option></select></label>
            <label class="field"><span>Reward type</span><select v-model="promotion.kind" data-testid="payment-promotion-kind" name="payment-kind"><option value="cash">Cashback</option><option value="asiamiles">Asia Miles</option><option value="membership_points">Membership points</option><option value="loyalty_points">Loyalty points</option></select></label>
            <label class="field"><span>{{ promotion.kind === 'cash' ? 'Cashback (%)' : promotion.kind === 'asiamiles' ? 'Asia Miles per HKD' : promotion.kind === 'membership_points' ? 'Membership points per HKD' : 'Loyalty points per HKD' }}</span><input :value="paymentRateValue(promotion)" data-testid="payment-promotion-rate" name="payment-rate" type="number" min="0" :max="promotion.kind === 'cash' ? 100 : 1000000" step="any" required @input="updatePaymentRate(promotion, $event.target.value)" /></label>
            <label class="field"><span>Merchant (optional; blank = all merchants)</span><input v-model="promotion.merchant" data-testid="payment-promotion-merchant" name="payment-merchant" placeholder="All merchants" /></label>
            <label><input v-model="promotion.enabled" data-testid="payment-promotion-enabled" name="payment-enabled" type="checkbox" /> Enabled</label>
            <button type="button" class="link-btn danger-text" data-testid="payment-promotion-remove" @click="paymentPromotions.splice(index, 1)">Remove payment promotion</button>
          </fieldset>
          <div class="actions">
            <button type="button" class="btn" data-testid="payment-promotion-add" :disabled="busy" @click="addPaymentPromotion()">Add payment promotion</button>
            <button type="button" class="btn" data-testid="payment-sample-mastercard-cashback" :disabled="busy" @click="addPaymentPromotion('cash', 0.024)">Add Mastercard cashback 2.4%</button>
            <button type="button" class="btn" data-testid="payment-sample-mastercard-asiamiles" :disabled="busy" @click="addPaymentPromotion('asiamiles', 0.1)">Add Mastercard Asia Miles 0.1/HKD</button>
          </div>
        </section>
        <div class="actions">
          <button type="button" class="btn" :disabled="busy" @click="addPromotion('Watsons', 150, 0.10)">Add Watsons 10% over HK$150</button>
          <button type="button" class="btn" :disabled="busy" @click="addPromotion('PARKnSHOP', 100, 0.15)">Add PARKnSHOP 15% over HK$100</button>
          <button type="button" class="btn" :disabled="busy" @click="addPromotion('', 0, 0, 'bogo')">Add buy 1 get 1</button>
          <button type="submit" class="btn primary" data-testid="market-save" :disabled="busy">Save promotions</button>
        </div>
      </form>
    </section>
    <section v-if="ready" class="card" data-testid="market-preview">
      <h2>Promotion preview</h2>
      <p class="muted small">Preview of unsaved form values. Checkout uses the saved market rules.</p>
      <label class="field"><span>Merchant subtotal (HK$)</span><input v-model.number="previewAmount" type="number" min="0" step="0.01" /></label>
      <p v-for="promotion in promotions" :key="promotion.id">
        <strong>{{ promotion.merchant }}</strong> ·
        <template v-if="!promotion.enabled">Disabled</template>
        <template v-else-if="promotion.kind === 'bogo'">Buy 1 {{ productById[promotion.sku]?.name || promotion.sku || 'selected product' }}, receive 1 free at {{ money(0) }}.</template>
        <template v-else>{{ previewAmount >= promotion.threshold ? money(previewAmount * (1 - promotion.rate)) : money(previewAmount) }} payable · {{ Math.round(promotion.rate * 100) }}% from {{ money(promotion.threshold) }}</template>
      </p>
    </section>
    <section class="card">
      <h2>Product price</h2>
      <form data-testid="market-product-form" @submit.prevent="saveProduct">
        <ProductPicker v-model="sku" @select="(product) => { price = product.price }" />
        <label class="field"><span>Price (HK$)</span><input v-model.number="price" name="price" type="number" min="0" step="0.01" required /></label>
        <button class="btn primary" data-testid="market-product-save" type="submit" :disabled="busy || !adminPassword || !sku.trim()">Save product</button>
      </form>
    </section>
  </main>
</template>

<style scoped>
.market-settings { max-width: 960px; margin: 0 auto; padding: 32px 20px; display: grid; gap: 20px; }
.promotion-row { margin: 20px 0; padding: 16px; border: 1px solid var(--line, #ddd); border-radius: 12px; display: grid; gap: 12px; }
form { display: grid; gap: 14px; }
.actions { flex-wrap: wrap; }
</style>
