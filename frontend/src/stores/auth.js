// Signed-in session.
// TODO(backend): replace logIn / register with calls to the accounts API.
// Until then this only keeps { name, email, phone } of the current session in the
// browser. Passwords are never stored or sent anywhere from here.
import { reactive, computed } from 'vue'

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

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

export async function logIn({ email, remember }) {
  await wait(600)
  setUser({ name: email.split('@')[0], email }, remember)
}

export async function register({ name, email, phone }) {
  await wait(800)
  setUser({ name, email, phone: phone || null })
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
