// Long-form content (About + legal documents) per language.
// Kept outside vue-i18n so legal text never goes through its message syntax.
import { computed } from 'vue'
import { i18n } from '../i18n/index.js'
import en from './en.js'
import zhHant from './zh-Hant.js'
import zhHans from './zh-Hans.js'

const byLocale = { en, 'zh-Hant': zhHant, 'zh-Hans': zhHans }

// Date the legal documents were last changed. Update when editing en/zh-Hant/zh-Hans.
export const LEGAL_UPDATED = '2026-10-03'

export const content = computed(() => byLocale[i18n.global.locale.value] ?? en)

// "{name}" placeholders in content strings.
export function fill(text, values) {
  return text.replace(/\{(\w+)\}/g, (_, key) => values[key] ?? '')
}
