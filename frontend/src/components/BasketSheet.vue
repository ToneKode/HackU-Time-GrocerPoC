<script setup>
import { computed, reactive } from 'vue'
import { useI18n } from 'vue-i18n'
import { money, lineArithmetic, lineReasons } from '../lib/format.js'
import * as api from '../lib/api.js'
import Icon from './shop/Icon.vue'
import { Cancel01Icon, MinusSignIcon, PlusSignIcon } from '@hugeicons/core-free-icons'

const props = defineProps({
  lines: { type: Array, default: () => [] },
  busy: Boolean,
  // plan.meal from the agent: request read, spend band, coverage, warnings.
  meal: { type: Object, default: null },
  // Latest policy result and the agent's question when the rules sent the basket back.
  policy: { type: Object, default: null },
  notice: { type: String, default: '' },
  intent: { type: String, default: '' },
})
const emit = defineEmits(['close', 'confirm', 'remove', 'qty', 'swap'])
const { t, te } = useI18n()

const openWhy = reactive({}) // sku -> reasons expanded
const swaps = reactive({}) // sku -> { loading, error, options }

const FREE_SHIPPING = 400
const SHIPPING_FEE = 30

const goods = computed(() => props.lines.reduce((sum, line) => sum + (Number(line.line_total) || 0), 0))
const estimate = computed(() => {
  if (!props.lines.length) return 0
  return goods.value + (goods.value >= FREE_SHIPPING ? 0 : SHIPPING_FEE)
})
const ceiling = computed(() => props.meal?.request?.max_total ?? props.meal?.ceiling ?? null)
const minimum = computed(() => props.meal?.minimum ?? null)
const band = computed(() => {
  if (ceiling.value == null) return null
  const total = estimate.value
  if (total > ceiling.value + 0.001) return 'over'
  if (minimum.value != null && total + 0.001 < minimum.value) return 'under'
  return 'in'
})
const bandPercent = computed(() => {
  if (!ceiling.value) return 0
  return Math.min(100, Math.round((estimate.value / ceiling.value) * 100))
})
const request = computed(() => props.meal?.request || null)
const coverage = computed(() => Object.entries(props.meal?.coverage || {}))
const blocked = computed(() => Boolean(props.notice) || props.policy?.status === 'HALT')

function groupLabel(key) {
  const path = `agentCards.groups.${key}`
  return te(path) ? t(path) : key
}
function mark(name) {
  const text = String(name || '?').trim()
  return text.slice(0, 1).toUpperCase()
}

async function loadSwaps(line) {
  if (swaps[line.sku]?.options) {
    delete swaps[line.sku]
    return
  }
  swaps[line.sku] = { loading: true, error: '', options: null }
  try {
    const body = await api.getAlternatives({
      intent: props.intent,
      sku: line.sku,
      exclude_skus: props.lines.map((item) => item.sku),
    })
    swaps[line.sku] = { loading: false, error: '', options: body.alternatives || [] }
  } catch (e) {
    swaps[line.sku] = { loading: false, error: e.message, options: [] }
  }
}
function pickSwap(line, option) {
  delete swaps[line.sku]
  delete openWhy[line.sku]
  emit('swap', line.sku, option)
}
</script>

<template>
  <div class="sheet-back" role="dialog" aria-modal="true" :aria-label="$t('agentCards.sheetTitle')">
    <header class="sheet-bar">
      <div>
        <p class="sheet-kicker">{{ $t('agentCards.sheetKicker') }}</p>
        <h2>{{ $t('agentCards.sheetTitle') }}</h2>
      </div>
      <button type="button" class="tile-x" :aria-label="$t('menu.close')" @click="emit('close')">
        <Icon :icon="Cancel01Icon" :size="18" />
      </button>
    </header>
    <p class="sheet-hint">{{ $t('agentCards.sheetHint') }}</p>

    <div v-if="blocked" class="sheet-alert" role="alert">
      <strong>{{ $t('agentCards.policyBlocked') }}</strong>
      <p>{{ notice || policy?.reason }}</p>
      <p v-if="policy?.rule" class="muted small">{{ $t('agentCards.policyRule', { rule: policy.rule }) }}</p>
    </div>
    <div v-else-if="policy?.status === 'PASS'" class="sheet-ok">{{ $t('agentCards.policyPassed') }}</div>

    <section v-if="meal" class="meal-band">
      <p v-if="request" class="muted small">
        {{ $t('agentCards.planRead', { days: request.days, family: request.family_size }) }}
        <span v-if="meal.strategy"> · {{ $t('agentCards.strategy', { name: meal.strategy }) }}</span>
      </p>
      <div v-if="ceiling != null" class="band-row">
        <span>{{ $t('agentCards.estTotal') }} <strong>{{ money(estimate) }}</strong></span>
        <span class="muted small">
          {{ minimum != null
            ? $t('agentCards.bandRange', { min: money(minimum), max: money(ceiling) })
            : $t('agentCards.bandMax', { max: money(ceiling) }) }}
        </span>
      </div>
      <div v-if="ceiling != null" class="band-bar" :class="`band-${band}`">
        <i :style="{ width: bandPercent + '%' }" />
      </div>
      <p v-if="band === 'over'" class="band-note band-over">{{ $t('agentCards.overMax') }}</p>
      <p v-else-if="band === 'under'" class="band-note band-under" role="status">
        {{ $t('agentCards.underMin', { short: money(minimum - estimate), total: money(estimate), min: money(minimum) }) }}
      </p>
      <p v-if="goods < FREE_SHIPPING && lines.length" class="muted small">{{ $t('agentCards.shippingNote', { fee: money(SHIPPING_FEE), free: money(FREE_SHIPPING) }) }}</p>
      <ul v-if="coverage.length" class="coverage-list">
        <li v-for="[group, value] in coverage" :key="group">
          {{ groupLabel(group) }} <strong>{{ Math.round(Math.min(value, 1) * 100) }}%</strong>
        </li>
      </ul>
      <ul v-if="meal.warnings?.length" class="band-note band-under">
        <li v-for="text in meal.warnings" :key="text">{{ text }}</li>
      </ul>
    </section>

    <div v-if="!lines.length" class="sheet-empty">{{ $t('agentCards.emptyBasket') }}</div>
    <div v-else class="tile-row" :class="{ 'meal-tiles': meal }">
      <article v-for="line in lines" :key="line.sku" class="product-tile">
        <button type="button" class="tile-x" :aria-label="$t('agentCards.removeItem', { name: line.name })" @click="emit('remove', line.sku)">
          <Icon :icon="Cancel01Icon" :size="16" />
        </button>
        <img v-if="line.image_url" class="tile-photo" :src="line.image_url" :alt="line.name" />
        <div v-else class="tile-photo tile-mark" aria-hidden="true">{{ mark(line.name) }}</div>
        <div class="tile-step">
          <button type="button" :aria-label="$t('card.removeOne')" :disabled="line.qty <= 1" @click="emit('qty', line.sku, line.qty - 1)">
            <Icon :icon="MinusSignIcon" :size="16" :stroke-width="2.2" />
          </button>
          <span>{{ line.qty }}</span>
          <button type="button" :aria-label="$t('card.addOne')" @click="emit('qty', line.sku, line.qty + 1)">
            <Icon :icon="PlusSignIcon" :size="16" :stroke-width="2.2" />
          </button>
        </div>
        <strong class="tile-name">{{ line.name }}</strong>
        <span class="muted small">{{ line.merchant }} · {{ money(line.unit_price) }}</span>
        <span class="tile-price">{{ money(line.line_total) }}</span>
        <p class="muted small pack-arithmetic" data-testid="pack-arithmetic">{{ lineArithmetic(line) }}</p>

        <div class="tile-actions">
          <button v-if="lineReasons(line).length" type="button" class="link-btn" :aria-expanded="Boolean(openWhy[line.sku])" @click="openWhy[line.sku] = !openWhy[line.sku]">
            {{ openWhy[line.sku] ? $t('agentCards.hideWhy') : $t('agentCards.whyItem') }}
          </button>
          <button type="button" class="link-btn" :disabled="swaps[line.sku]?.loading" @click="loadSwaps(line)">
            {{ swaps[line.sku]?.options ? $t('agentCards.cancelSwap') : $t('agentCards.swap') }}
          </button>
        </div>
        <div v-if="openWhy[line.sku]" class="tile-why" :data-sku="line.sku" data-testid="basket-product-reason">
          <p v-for="part in lineReasons(line)" :key="part">{{ part }}</p>
        </div>
        <div v-if="swaps[line.sku]" class="tile-swaps">
          <p v-if="swaps[line.sku].loading" class="muted small">{{ $t('agentCards.swapLoading') }}</p>
          <p v-else-if="swaps[line.sku].error" class="muted small">{{ swaps[line.sku].error }}</p>
          <p v-else-if="!swaps[line.sku].options?.length" class="muted small">{{ $t('agentCards.swapNone') }}</p>
          <ul v-else>
            <li v-for="option in swaps[line.sku].options" :key="option.sku">
              <button type="button" class="swap-option" @click="pickSwap(line, option)">
                <strong>{{ option.name }}</strong>
                <span class="muted small">{{ option.merchant }} · {{ money(option.price) }}</span>
                <em>{{ option.reason }}</em>
              </button>
            </li>
          </ul>
        </div>
      </article>
    </div>

    <footer class="sheet-foot">
      <button type="button" class="btn primary sheet-confirm" :disabled="busy || !lines.length" @click="emit('confirm')">
        {{ blocked ? $t('agentCards.recheckBasket') : $t('agentCards.confirmBasket') }}
      </button>
    </footer>
  </div>
</template>
