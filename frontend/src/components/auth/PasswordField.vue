<script setup>
import { ref } from 'vue'
import Icon from '../shop/Icon.vue'
import { SquareLock02Icon, ViewIcon, ViewOffIcon } from '@hugeicons/core-free-icons'

defineProps({
  id: { type: String, required: true },
  autocomplete: { type: String, default: 'current-password' },
  invalid: Boolean,
  describedby: { type: String, default: undefined },
})
const value = defineModel({ type: String, default: '' })
const visible = ref(false)
</script>

<template>
  <div class="auth-input" :class="{ invalid }">
    <Icon :icon="SquareLock02Icon" :size="18" class="auth-input-icon" />
    <input
      :id="id"
      v-model="value"
      :type="visible ? 'text' : 'password'"
      :autocomplete="autocomplete"
      :aria-invalid="invalid"
      :aria-describedby="describedby"
    />
    <button
      type="button"
      class="auth-eye"
      :aria-label="visible ? $t('auth.hidePassword') : $t('auth.showPassword')"
      :aria-pressed="visible"
      @click="visible = !visible"
    >
      <Icon :icon="visible ? ViewOffIcon : ViewIcon" :size="18" />
    </button>
  </div>
</template>
