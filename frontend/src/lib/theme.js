// Theme preference: 'system' | 'light' | 'dark', saved in the browser.
// The resolved theme is written to <html data-theme="light|dark">; CSS reads that.
// index.html runs the same logic inline before the page paints, so there is no flash.
import { ref, computed } from 'vue'

const STORAGE_KEY = 'tg-theme'
export const THEMES = ['system', 'light', 'dark']

const media = window.matchMedia('(prefers-color-scheme: dark)')

function load() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return THEMES.includes(saved) ? saved : 'system'
  } catch {
    return 'system'
  }
}

export const themePref = ref(load())
const systemDark = ref(media.matches)
export const resolvedTheme = computed(() =>
  themePref.value === 'system' ? (systemDark.value ? 'dark' : 'light') : themePref.value,
)

function apply() {
  document.documentElement.dataset.theme = resolvedTheme.value
}

export function setTheme(pref) {
  themePref.value = pref
  try {
    localStorage.setItem(STORAGE_KEY, pref)
  } catch {
    // Not saved, but the theme still applies for this visit.
  }
  apply()
}

// Follow OS changes while on "System".
media.addEventListener('change', (event) => {
  systemDark.value = event.matches
  apply()
})

apply()
