// Languages: English, Traditional Chinese (HK), Simplified Chinese.
// UI strings live in en.js / zh-Hant.js / zh-Hans.js; product + store names in products.js.
import { createI18n } from 'vue-i18n'
import en from './en.js'
import zhHant from './zh-Hant.js'
import zhHans from './zh-Hans.js'
import productsZh, { storeNamesZh, policyReasonsZh } from './products.js'
import { categoryById } from '../data/catalog.js'

export const LOCALES = [
  { code: 'en', label: 'English', date: 'en-HK' },
  { code: 'zh-Hant', label: '繁體中文', date: 'zh-HK' },
  { code: 'zh-Hans', label: '简体中文', date: 'zh-CN' },
]
const STORAGE_KEY = 'tg-locale'

function initialLocale() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (LOCALES.some((l) => l.code === saved)) return saved
  } catch {
    // Storage blocked: fall through to the browser language.
  }
  const browser = (navigator.languages?.[0] ?? navigator.language ?? 'en').toLowerCase()
  if (browser.startsWith('zh')) return /hant|tw|hk|mo/.test(browser) ? 'zh-Hant' : 'zh-Hans'
  return 'en'
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale(),
  fallbackLocale: 'en',
  messages: { en, 'zh-Hant': zhHant, 'zh-Hans': zhHans },
})

const locale = i18n.global.locale
document.documentElement.lang = locale.value

export function setLocale(code) {
  locale.value = code
  document.documentElement.lang = code
  try {
    localStorage.setItem(STORAGE_KEY, code)
  } catch {
    // Not saved, but the switch still applies for this visit.
  }
}

// Index into the [Traditional, Simplified] pairs, or -1 for English.
const zhIndex = () => (locale.value === 'zh-Hant' ? 0 : locale.value === 'zh-Hans' ? 1 : -1)

export const dateLocale = () => LOCALES.find((l) => l.code === locale.value)?.date ?? 'en-HK'

export function productName(product) {
  const i = zhIndex()
  return (i >= 0 && productsZh[product.id]?.name[i]) || product.name
}

export function productSize(product) {
  const i = zhIndex()
  return (i >= 0 && productsZh[product.id]?.size?.[i]) || product.size
}

export function storeName(name) {
  const i = zhIndex()
  return (i >= 0 && storeNamesZh[name]?.[i]) || name
}

export function policyReason(text) {
  const i = zhIndex()
  return (i >= 0 && policyReasonsZh[text]?.[i]) || text
}

export function categoryLabel(id) {
  const key = `category.${id}`
  if (i18n.global.te(key)) return i18n.global.t(key)
  return categoryById[id]?.label || id
}

// "A, B and C" style list in the current language.
export function listOf(items) {
  return new Intl.ListFormat(locale.value, { style: 'long', type: 'conjunction' }).format(items)
}
