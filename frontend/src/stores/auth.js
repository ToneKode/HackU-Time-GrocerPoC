// Signed-in session. The password is checked by the persistance API and is
// never written here. The browser keeps the account id and the spending caps.
import { reactive, computed } from 'vue'
import { loginAccount, registerAccount } from '../lib/api.js'

const STORAGE_KEY = 'tg-session'

function load() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY))
  } catch {
    return null
  }
}

export const session = reactive({ user: load() })
export const isLoggedIn = computed(() => Boolean(session.user))

function setUser(user, remember = true) {
  session.user = user
  try {
    if (user && remember) localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Storage blocked: the session lasts for this visit only.
  }
}

function sessionUser(profile) {
  return {
    id: profile.id,
    email: profile.email,
    name: profile.name,
    phone: profile.phone || null,
    membership: profile.membership,
    monthly_cap: profile.monthly_cap,
    per_order_cap: profile.per_order_cap,
    bulk_ceiling: profile.bulk_ceiling,
  }
}

export async function logIn({ email, password, remember }) {
  const profile = await loginAccount({ email, password })
  setUser(sessionUser(profile), remember)
}

export async function register({ name, email, phone, password, marketing }) {
  const profile = await registerAccount({
    name,
    email,
    phone: phone || '',
    password,
    marketing: Boolean(marketing),
  })
  setUser(sessionUser(profile), true)
}

export function logOut() {
  setUser(null)
}

// Basic checks shared by the forms.
export const isEmail = (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim())
export const isHkMobile = (value) => /^[2-9]\d{7}$/.test(value.replace(/\s/g, ''))

// 0 = empty, 1 = weak, 2 = fair, 3 = strong
export function passwordStrength(value) {
  if (!value) return 0
  let score = 0
  if (value.length >= 8) score++
  if (/[A-Za-z]/.test(value) && /\d/.test(value)) score++
  if (value.length >= 12 || /[^A-Za-z0-9]/.test(value)) score++
  return Math.max(1, score)
}
