<script setup>
import { ref, reactive, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { register, isEmail, isHkMobile, passwordStrength } from '../stores/auth.js'
import AuthShell from '../components/auth/AuthShell.vue'
import PasswordField from '../components/auth/PasswordField.vue'
import Icon from '../components/shop/Icon.vue'
import { Mail01Icon, UserIcon, SmartPhone01Icon, UserAdd01Icon } from '@hugeicons/core-free-icons'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()

// marketing is opt-in and unticked by default (PDPO Part 6A).
const form = reactive({ name: '', email: '', phone: '', password: '', terms: false, marketing: false })
const submitted = ref(false)
const busy = ref(false)

const strength = computed(() => passwordStrength(form.password))
const strengthKey = computed(() => ['', 'weak', 'fair', 'strong'][strength.value])

const errors = computed(() => ({
  name: !form.name.trim() ? t('auth.errors.required') : '',
  email: !form.email.trim() ? t('auth.errors.required') : !isEmail(form.email) ? t('auth.errors.email') : '',
  phone: form.phone.trim() && !isHkMobile(form.phone) ? t('auth.errors.phone') : '',
  password: !form.password ? t('auth.errors.required') : form.password.length < 8 ? t('auth.errors.passwordShort') : '',
  terms: !form.terms ? t('auth.errors.terms') : '',
}))
const show = (field) => submitted.value && errors.value[field]

async function submit() {
  submitted.value = true
  if (Object.values(errors.value).some(Boolean)) return
  busy.value = true
  try {
    await register({
      name: form.name.trim(),
      email: form.email.trim(),
      phone: form.phone.replace(/\s/g, ''),
      password: form.password,
      marketing: form.marketing,
    })
    router.push(route.query.redirect || '/')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <AuthShell variant="register" :title="$t('auth.registerTitle')" :subtitle="$t('auth.registerSubtitle')">
    <form class="auth-form" novalidate @submit.prevent="submit">
      <div class="auth-field">
        <label for="reg-name">{{ $t('auth.name') }}</label>
        <div class="auth-input" :class="{ invalid: show('name') }">
          <Icon :icon="UserIcon" :size="18" class="auth-input-icon" />
          <input
            id="reg-name"
            v-model="form.name"
            type="text"
            autocomplete="name"
            :aria-invalid="Boolean(show('name'))"
            aria-describedby="reg-name-error"
          />
        </div>
        <p v-if="show('name')" id="reg-name-error" class="auth-error">{{ errors.name }}</p>
      </div>

      <div class="auth-field">
        <label for="reg-email">{{ $t('auth.email') }}</label>
        <div class="auth-input" :class="{ invalid: show('email') }">
          <Icon :icon="Mail01Icon" :size="18" class="auth-input-icon" />
          <input
            id="reg-email"
            v-model="form.email"
            type="email"
            autocomplete="email"
            inputmode="email"
            :placeholder="$t('auth.emailPlaceholder')"
            :aria-invalid="Boolean(show('email'))"
            aria-describedby="reg-email-error"
          />
        </div>
        <p v-if="show('email')" id="reg-email-error" class="auth-error">{{ errors.email }}</p>
      </div>

      <div class="auth-field">
        <label for="reg-phone">{{ $t('auth.phone') }} <span class="muted">({{ $t('auth.optional') }})</span></label>
        <div class="auth-input" :class="{ invalid: show('phone') }">
          <Icon :icon="SmartPhone01Icon" :size="18" class="auth-input-icon" />
          <span class="auth-prefix">+852</span>
          <input
            id="reg-phone"
            v-model="form.phone"
            type="tel"
            autocomplete="tel-national"
            inputmode="numeric"
            maxlength="9"
            :aria-invalid="Boolean(show('phone'))"
            aria-describedby="reg-phone-hint"
          />
        </div>
        <p v-if="show('phone')" id="reg-phone-hint" class="auth-error">{{ errors.phone }}</p>
        <p v-else id="reg-phone-hint" class="auth-hint">{{ $t('auth.phoneHint') }}</p>
      </div>

      <div class="auth-field">
        <label for="reg-password">{{ $t('auth.password') }}</label>
        <PasswordField
          id="reg-password"
          v-model="form.password"
          autocomplete="new-password"
          :invalid="Boolean(show('password'))"
          describedby="reg-password-hint"
        />
        <div v-if="form.password" class="auth-strength" :class="`s-${strengthKey}`">
          <span v-for="n in 3" :key="n" :class="{ on: n <= strength }" />
          <em>{{ $t('auth.strengthLabel', { level: $t(`auth.strength.${strengthKey}`) }) }}</em>
        </div>
        <p v-if="show('password')" id="reg-password-hint" class="auth-error">{{ errors.password }}</p>
        <p v-else id="reg-password-hint" class="auth-hint">{{ $t('auth.newPasswordHint') }}</p>
      </div>

      <label class="auth-check" :class="{ invalid: show('terms') }">
        <input v-model="form.terms" type="checkbox" :aria-invalid="Boolean(show('terms'))" aria-describedby="reg-terms-error" />
        <i18n-t keypath="auth.agreeTerms" tag="span">
          <template #terms><RouterLink to="/terms" target="_blank">{{ $t('auth.termsLink') }}</RouterLink></template>
          <template #privacy><RouterLink to="/privacy" target="_blank">{{ $t('auth.privacyLink') }}</RouterLink></template>
        </i18n-t>
      </label>
      <p v-if="show('terms')" id="reg-terms-error" class="auth-error">{{ errors.terms }}</p>

      <label class="auth-check">
        <input v-model="form.marketing" type="checkbox" />
        <span>{{ $t('auth.marketing') }}</span>
      </label>

      <button type="submit" class="btn-primary auth-submit" :disabled="busy">
        <Icon :icon="UserAdd01Icon" :size="18" /> {{ busy ? $t('auth.registering') : $t('auth.register') }}
      </button>
    </form>

    <p class="auth-switch">
      {{ $t('auth.haveAccount') }}
      <RouterLink :to="{ name: 'login', query: route.query }">{{ $t('auth.loginLink') }}</RouterLink>
    </p>
  </AuthShell>
</template>
