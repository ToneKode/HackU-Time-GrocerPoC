<script setup>
import { merchants } from '../../data/catalog.js'
import MerchantLogo from './MerchantLogo.vue'
import { storeName } from '../../i18n/index.js'

// multiple=false: v-model is a merchant name or null (= all stores)
// multiple=true:  v-model is an array of selected merchant names
const props = defineProps({ multiple: Boolean })
const model = defineModel()

function isOn(name) {
  return props.multiple ? model.value.includes(name) : model.value === name
}

function toggle(name) {
  if (!props.multiple) {
    model.value = model.value === name ? null : name
    return
  }
  model.value = isOn(name) ? model.value.filter((n) => n !== name) : [...model.value, name]
}
</script>

<template>
  <div class="chips-row">
    <button
      v-if="!multiple"
      type="button"
      class="store-chip"
      :class="{ on: model == null }"
      @click="model = null"
    >
      {{ $t('stores.all') }}
    </button>
    <button
      v-for="m in merchants"
      :key="m.name"
      type="button"
      class="store-chip"
      :class="{ on: isOn(m.name) }"
      :aria-pressed="isOn(m.name)"
      @click="toggle(m.name)"
    >
      <MerchantLogo :name="m.name" :size="22" />
      {{ storeName(m.name) }}
    </button>
  </div>
</template>
