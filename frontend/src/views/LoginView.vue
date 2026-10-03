<script setup>
import { ref, reactive, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { logIn, isEmail } from '../stores/auth.js'
import AuthShell from '../components/auth/AuthShell.vue'
import PasswordField from '../components/auth/PasswordField.vue'
import Icon from '../components/shop/Icon.vue'
import { Mail01Icon, Login01Icon } from '@hugeicons/core-free-icons'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

const form = reactive({ email: '', password: '', remember: true })
const submitted = ref(false)
const busy = ref(false)

const errors = computed(() => ({
  email: !form.email.trim() ? t('auth.errors.required') : !isEmail(form.email) ? t('auth.errors.email') : '',
  password: !form.password ? t('auth.errors.required') : '',
}))
const show = (field) => submitted.value && errors.value[field]

async function submit() {
  submitted.value = true
  if (errors.value.email || errors.value.password) return
  busy.value = true
  try {
    await logIn({ email: form.email.trim(), password: form.password, remember: form.remember })
    router.push(route.query.redirect || '/')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthShell variant="login" :title="$t('auth.loginTitle')" :subtitle="$t('auth.loginSubtitle')">
    <form class="auth-form" novalidate @submit.prevent="submit">
      <div class="auth-field">
        <label for="login-email">{{ $t('auth.email') }}</label>
        <div class="auth-input" :class="{ invalid: show('email') }">
          <Icon :icon="Mail01Icon" :size="18" class="auth-input-icon" />
          <input
            id="login-email"
            v-model="form.email"
            type="email"
            autocomplete="email"
            inputmode="email"
            :placeholder="$t('auth.emailPlaceholder')"
            :aria-invalid="Boolean(show('email'))"
            aria-describedby="login-email-error"
          />
        </div>
        <p v-if="show('email')" id="login-email-error" class="auth-error">{{ errors.email }}</p>
      </div>

      <div class="auth-field">
        <label for="login-password">{{ $t('auth.password') }}</label>
        <PasswordField
          id="login-password"
          v-model="form.password"
          autocomplete="current-password"
          :invalid="Boolean(show('password'))"
          describedby="login-password-error"
        />
        <p v-if="show('password')" id="login-password-error" class="auth-error">{{ errors.password }}</p>
      </div>

      <label class="auth-check">
        <input v-model="form.remember" type="checkbox" />
        <span>{{ $t('auth.remember') }}</span>
      </label>

      <button type="submit" class="btn-primary auth-submit" :disabled="busy">
        <Icon :icon="Login01Icon" :size="18" /> {{ busy ? $t('auth.loggingIn') : $t('auth.logIn') }}
      </button>
    </form>

    <p class="auth-switch">
      {{ $t('auth.noAccount') }}
      <RouterLink :to="{ name: 'register', query: route.query }">{{ $t('auth.registerLink') }}</RouterLink>
    </p>
  </AuthShell>
</template>
