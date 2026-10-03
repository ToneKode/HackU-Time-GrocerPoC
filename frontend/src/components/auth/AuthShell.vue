<script setup>
// Two-column auth layout: form on the left, food illustration on the right
// (on phones the illustration becomes a banner above the form).
import { useRouter } from 'vue-router'
import AuthArt from './AuthArt.vue'
import Icon from '../shop/Icon.vue'
import { ArrowLeft01Icon } from '@hugeicons/core-free-icons'

defineProps({
  variant: { type: String, default: 'login' },
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
})

const router = useRouter()

// Go back to where the user came from; if they landed here directly, go home.
function goBack() {
  if (window.history.state?.back) router.back()
  else router.push('/')
}
</script>

<template>
  <main class="auth-page">
    <button type="button" class="auth-back" @click="goBack">
      <Icon :icon="ArrowLeft01Icon" :size="18" /> {{ $t('auth.back') }}
    </button>
    <section class="auth-form-side">
      <div class="auth-form-wrap">
        <h1 class="auth-title">{{ title }}</h1>
        <p v-if="subtitle" class="auth-subtitle">{{ subtitle }}</p>
        <slot />
      </div>
    </section>
    <aside class="auth-art-side" :class="`auth-art-${variant}`">
      <AuthArt :variant="variant" />
    </aside>
  </main>
</template>
