<script setup>
import { money } from '../lib/format.js'
import { productName, storeName } from '../i18n/index.js'

defineProps({ plan: { type: Object, required: true } })
</script>

<template>
  <section class="card">
    <h2>{{ plan.payment ? $t('agentCards.orderTitle') : $t('agentCards.basketTitle') }}</h2>
    <!-- Product names are untrusted plain text: always {{ }}, never v-html. -->
    <ul v-if="plan.lines?.length" class="basket-lines">
      <li v-for="line in plan.lines" :key="line.sku">
        {{ productName({ id: line.sku, name: line.name }) }}
        <span class="muted"> · {{ storeName(line.merchant) }} · ×{{ line.qty }} · {{ money(line.line_total) }}</span>
      </li>
    </ul>
    <p v-else-if="plan.product" class="product-name">{{ productName(plan.product) }}</p>
    <dl class="rows">
      <template v-if="!plan.lines?.length && plan.product">
        <dt>{{ $t('agentCards.merchant') }}</dt><dd>{{ storeName(plan.product.merchant) }}</dd>
      </template>
      <template v-if="plan.payment">
        <dt>{{ $t('agentCards.orderId') }}</dt><dd class="mono">{{ plan.payment.order_id }}</dd>
      </template>
      <dt>{{ $t('agentCards.subtotal') }}</dt><dd>{{ money(plan.quote?.subtotal) }}</dd>
      <dt>{{ $t('agentCards.shipping') }}</dt><dd>{{ money(plan.quote?.shipping_fee) }}</dd>
      <dt class="total">{{ plan.payment ? $t('agentCards.charged') : $t('agentCards.landed') }}</dt>
      <dd class="total">{{ money(plan.payment?.charged ?? plan.quote?.total_landed_cost) }}</dd>
    </dl>
  </section>
</template>
