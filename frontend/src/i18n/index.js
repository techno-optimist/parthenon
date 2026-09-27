import { watch } from 'vue'
import { createI18n } from 'vue-i18n'
import languages from '../../../locales/languages.json'
import { setVocabularyLocale, followVocabularyLocale } from '../parthenon/vocabulary.js'

const localeFiles = import.meta.glob('../../../locales/!(languages).json', { eager: true })

const messages = {}
const availableLocales = []

for (const path in localeFiles) {
  const key = path.match(/\/([^/]+)\.json$/)[1]
  if (languages[key]) {
    messages[key] = localeFiles[path].default
    availableLocales.push({ key, label: languages[key].label })
  }
}

const readSaved = () => {
  try {
    return localStorage.getItem('locale') || 'en'
  } catch {
    return 'en'
  }
}

const savedLocale = readSaved()

const i18n = createI18n({
  legacy: false,
  locale: savedLocale,
  fallbackLocale: 'en',
  messages
})

// The Chinese serif, fetched the first time the visitor reads in Chinese
// (index.html fetches it before first paint when the visit starts in Chinese).
const CJK_FONT = 'https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600&display=swap'
const ensureChineseFont = () => {
  if (typeof document === 'undefined') return
  if (document.querySelector(`link[href="${CJK_FONT}"]`)) return
  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.href = CJK_FONT
  document.head.appendChild(link)
}

// One place keeps the city's words, <html lang> and the fonts in step with
// the visitor's language, at start and on every change.
const followLocale = (locale) => {
  const key = String(locale || 'en')
  setVocabularyLocale(key)
  if (typeof document !== 'undefined') {
    document.documentElement.lang = key
    if (key.startsWith('zh')) ensureChineseFont()
  }
}

followLocale(i18n.global.locale.value)
// Views that call the vocabulary re-render when the language changes.
followVocabularyLocale(() => i18n.global.locale.value)
// Synchronous, so the vocabulary has changed before anything re-renders.
watch(() => i18n.global.locale.value, followLocale, { flush: 'sync' })

export { availableLocales }
export default i18n
