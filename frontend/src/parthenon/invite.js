// The word that opens the steps to speech.
//
// On the public steps anyone with the link may walk the exhibits and read
// every gathering; to begin a gathering or to put a question (to a citizen,
// the Scribe, the one who had the floor, the Oracle), a visitor brings the
// word the owner gave them. The page asks for it only when it is needed, keeps
// it in localStorage 'parthenon.invite', and shows it as X-Parthenon-Invite on
// the calls the city guards with it. A link may carry it (?invite=CODE): the
// page takes it in and clears it from the address bar before anything else.
//
// Pure functions over a storage, a URL and a request, so node can test them.

export const INVITE_KEY = 'parthenon.invite'
export const INVITE_HEADER = 'X-Parthenon-Invite'
export const INVITE_PARAM = 'invite'

// Printable ASCII only (a header value), no comma (the owner's list is comma
// separated), at most 256 characters once trimmed.
const PRINTABLE = /^[\x20-\x7e]{1,256}$/

/** The word as the page keeps it, or '' when it could not be one. */
export const cleanInvite = (value) => {
  if (typeof value !== 'string') return ''
  const code = value.trim()
  if (!code || !PRINTABLE.test(code) || code.includes(',')) return ''
  return code
}

export const readInvite = (storage) => {
  try {
    return cleanInvite(storage?.getItem(INVITE_KEY) ?? '')
  } catch {
    return ''
  }
}

export const writeInvite = (storage, code) => {
  const clean = cleanInvite(code)
  if (!clean) return false
  try {
    storage?.setItem(INVITE_KEY, clean)
    return true
  } catch {
    return false
  }
}

export const forgetInvite = (storage) => {
  try {
    storage?.removeItem(INVITE_KEY)
    return true
  } catch {
    return false
  }
}

const decode = (text) => {
  try {
    return decodeURIComponent(text)
  } catch {
    return null
  }
}

/**
 * The word a link carries (?invite=CODE), and the address without it: the
 * other parameters and the hash are kept exactly as they were. A '+' in the
 * word is kept as a '+' (a code is not a phrase). Returns { code: '', url: '' }
 * when the link carries none; { code: '', url } when it carries one that
 * cannot be a word (the address is still cleared of it).
 */
export const inviteInLink = (href) => {
  let u
  try {
    u = new URL(String(href || ''))
  } catch {
    return { code: '', url: '' }
  }
  const raw = u.search.startsWith('?') ? u.search.slice(1) : u.search
  if (!raw) return { code: '', url: '' }
  let found = false
  let code = ''
  const kept = []
  for (const part of raw.split('&')) {
    if (!part) continue
    const eq = part.indexOf('=')
    const key = decode(eq < 0 ? part : part.slice(0, eq))
    if (key === INVITE_PARAM) {
      found = true
      if (!code) code = cleanInvite(decode(eq < 0 ? '' : part.slice(eq + 1)) ?? '')
      continue
    }
    kept.push(part)
  }
  if (!found) return { code: '', url: '' }
  const search = kept.length ? `?${kept.join('&')}` : ''
  return { code, url: `${u.pathname}${search}${u.hash}` }
}

// The calls the city guards with the word: beginning a gathering, every
// question (a citizen, the crowd, the Scribe, the one who had the floor), the
// Oracle's draft, and making something new (faces, a film, a stance reading, a
// voice). Reading never needs it.
const INVITED = [
  /^\/api\/graph\/ontology\/generate$/,
  /^\/api\/simulation\/interview(?:\/batch|\/all)?$/,
  /^\/api\/report\/chat$/,
  /^\/api\/parthenon\/stage\/draft$/,
  /^\/api\/parthenon\/voice$/,
  /^\/api\/parthenon\/gathering\/[^/?#]+\/(?:speaker|portraits|stances)$/,
  /^\/api\/parthenon\/chronicle\/[^/?#]+\/film$/
]

/** The API path of a request's url ('/api/...'), whatever base or origin is in front of it. */
export const apiPathOf = (url) => {
  const text = String(url || '').split(/[?#]/)[0]
  const at = text.search(/\/api\//)
  return at < 0 ? '' : text.slice(at)
}

/** Does this request need the word? Only a POST to one of the guarded routes. */
export const isInvitedCall = (config = {}) => {
  if (String(config.method || 'get').toLowerCase() !== 'post') return false
  const path = apiPathOf(config.url)
  return !!path && INVITED.some((re) => re.test(path))
}

/**
 * Bring the slip into view whole, clear of the fixed header and the act bar
 * (its scroll-margin), at once and only when it is not already in view. Also
 * used when a calm line (a word not known, a limit) grows the slip at its foot.
 * Returns whether the slip could be asked to show itself.
 */
export const showSlip = (slip) => {
  if (!slip || typeof slip.scrollIntoView !== 'function') return false
  try {
    slip.scrollIntoView({ block: 'nearest', inline: 'nearest', behavior: 'auto' })
    return true
  } catch {
    return false
  }
}

/**
 * Show the slip where the visitor can use it, then give its field the caret.
 * The slip is brought into view whole (its field and its 'Give the word'),
 * clear of the fixed header and the act bar, which its own scroll-margin
 * names; only then is the field focused, without a scroll of its own, so the
 * browser's focus scroll cannot leave the field under the act bar on a phone.
 * Scrolls only when the slip is not already in view (block 'nearest'), and
 * at once: a smooth scroll can be cut short (by the phone's keyboard rising
 * for the field, by another scroll, in a tab out of sight) and leave the slip
 * where it was. Returns whether the field took the focus.
 */
export const presentSlip = (slip, field) => {
  showSlip(slip)
  if (!field || typeof field.focus !== 'function') return false
  try {
    field.focus({ preventScroll: true })
    return true
  } catch {
    return false
  }
}
