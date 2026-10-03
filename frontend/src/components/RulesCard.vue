<script setup>
import { storeName } from '../i18n/index.js'

defineProps({ rules: { type: Array, required: true } })
</script>

<template>
  <section class="card">
    <h2>{{ $t('agentCards.rulesTitle') }}</h2>
    <dl class="rows">
      <template v-for="rule in rules" :key="rule.id">
        <dt>{{ $te(`agentCards.rules.${rule.id}`) ? $t(`agentCards.rules.${rule.id}`) : rule.label }}</dt>
        <dd v-if="rule.merchants" class="chips">
          <span v-for="m in rule.merchants" :key="m" class="chip" :class="{ 'chip-bad': rule.id === 'blacklist' }">{{ storeName(m) }}</span>
        </dd>
        <dd v-else>{{ rule.display }}</dd>
      </template>
    </dl>
  </section>
</template>
