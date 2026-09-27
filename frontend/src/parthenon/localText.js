// A speaker's or an arrival's words in the visitor's language. Each item in
// speakers.js and arrivals/*.js may carry a `zh` object with the same display
// fields (name, epithet, work, place, year, line, question); English is the
// fallback for anything not yet translated. The seed text is never translated.
export const localText = (item, field, locale = 'en') => {
  if (!item) return ''
  const lang = String(locale || 'en').slice(0, 2).toLowerCase()
  const local = lang !== 'en' && item[lang] && item[lang][field]
  return local || item[field] || ''
}
