<script setup>
import { money } from '../lib/format.js'
import { productName, storeName } from '../i18n/index.js'

defineProps({ plan: { type: Object, required: true } })
</script>

<template>
  <section class="card">
    <h2>{{ $t('agentCards.orderTitle') }}</h2>
    <!-- Product names are untrusted plain text: always {{ }}, never v-html. -->
    <p class="product-name">{{ productName(plan.product) }}</p>
    <dl class="rows">
      <dt>{{ $t('agentCards.merchant') }}</dt><dd>{{ storeName(plan.product.merchant) }}</dd>
      <dt>{{ $t('agentCards.orderId') }}</dt><dd class="mono">{{ plan.payment.order_id }}</dd>
      <dt>{{ $t('agentCards.subtotal') }}</dt><dd>{{ money(plan.quote?.subtotal) }}</dd>
      <dt>{{ $t('agentCards.shipping') }}</dt><dd>{{ money(plan.quote?.shipping_fee) }}</dd>
      <dt class="total">{{ $t('agentCards.charged') }}</dt><dd class="total">{{ money(plan.payment.charged) }}</dd>
    </dl>
  </section>
</template>
