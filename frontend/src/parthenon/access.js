// What this visitor may do here, in one reactive place: whether the city is on
// the public steps, what it can still make there (faces, films, voices), its
// limits for the day, and which gatherings this browser began.
//
// On the owner's own machine (not public) everything is as it always was:
// every control shows, every feature is on, no key is ever sent.
import { reactive } from 'vue'
import { PUBLIC_BUILD } from './base.js'
import {
  OWNED_KEY,
  ADMIN_KEY,
  readOwned,
  writeOwned,
  readAdmin,
  addOwned,
  learnFromResponse,
  tokenFor,
  listedIds,
  ownsAny
} from './owned.js'
import { INVITE_KEY, cleanInvite, readInvite, writeInvite, forgetInvite } from './invite.js'
import { linkedInvite } from './inviteLink.js'

const storage = () => {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null
  } catch {
    return null
  }
}

export const FEATURES = ['portraits', 'film', 'voice']
export const CITY_CODES = ['city_full', 'come_back_tomorrow', 'slow_down', 'too_long', 'not_yours', 'not_on_public_steps', 'invite_needed', 'ticket_lost']

export const access = reactive({
  // The city's own account of itself (GET /api/parthenon/status) has arrived.
  loaded: false,
  // Until it arrives a public build assumes the public steps, and makes nothing new.
  public: PUBLIC_BUILD,
  provider: '',
  features: { portraits: !PUBLIC_BUILD, film: !PUBLIC_BUILD, voice: !PUBLIC_BUILD },
  limits: null,
  owned: readOwned(storage()),
  admin: readAdmin(storage()),
  // The word that opens the steps to speech (parthenon/invite.js): whether the
  // city asks for it, the one this browser keeps, and whether the last one
  // given was not known.
  inviteRequired: false,
  invite: readInvite(storage()) || linkedInvite,
  inviteWrong: false
})

// Another tab of this browser began a gathering or was given the admin key.
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('storage', (event) => {
    if (event.key === OWNED_KEY || event.key === null) access.owned = readOwned(storage())
    if (event.key === ADMIN_KEY || event.key === null) access.admin = readAdmin(storage())
    if (event.key === INVITE_KEY || event.key === null) {
      access.invite = readInvite(storage())
      if (access.invite) access.inviteWrong = false
    }
  })
}

const keep = (next) => {
  if (next === access.owned) return
  // Read again first: another tab may have kept a gathering meanwhile.
  const merged = { ...readOwned(storage()), ...next }
  access.owned = merged
  writeOwned(storage(), merged)
}

/** Keep these ids of one gathering under its key. */
export const rememberOwned = (ids, token) => keep(addOwned(access.owned, ids, token))

/** What a response taught: a key handed back, or new ids of a gathering this browser began. */
export const learnOwnership = (sentToken, body) => keep(learnFromResponse(access.owned, { sentToken, body }))

/** The key to show for a call about these ids, or ''. */
export const ownerTokenFor = (ids) => tokenFor(access.owned, ids)

/** The ids to tell the shelf about: the ones asked for, then the ones this browser began. */
export const shelfIds = (extra = []) => listedIds(access.owned, extra)

/** Did this browser begin this gathering (any of its ids)? */
export const ownsGathering = (...ids) => ownsAny(access.owned, ids.flat().filter(Boolean))

/**
 * May this visitor steer the gathering (start, stop, film, paint, rewrite)?
 * Always on the owner's own machine; on the public steps, only the one who
 * began it, or the city's keeper (the admin key in this browser).
 */
export const canControl = (...ids) => !access.public || !!access.admin || ownsGathering(...ids)

/** Can new faces, films or voices be made here? Always on the owner's own machine. */
export const featureOn = (name) => !access.public || access.features?.[name] === true

/** Take in the city's account of itself. */
export const applyStatus = (data) => {
  if (!data || typeof data !== 'object') return
  access.loaded = true
  access.public = data.public === true
  access.provider = typeof data.provider === 'string' ? data.provider : ''
  const features = data.features && typeof data.features === 'object' ? data.features : null
  for (const name of FEATURES) {
    // A server that says nothing of its features (an older backend) can make everything.
    access.features[name] = features ? features[name] === true : true
  }
  access.limits = data.limits && typeof data.limits === 'object' ? { ...data.limits } : null
  access.inviteRequired = data.invite_required === true
}

/**
 * Must the visitor bring the word before this (beginning a gathering, a
 * question, the Oracle)? Only when the city asks for one, this browser keeps
 * none, and it is not the city's keeper. When the city asks for none, nothing
 * changes anywhere.
 */
export const inviteNeeded = () => access.inviteRequired === true && !access.invite && !access.admin

/** Keep the word the visitor brought. False when it cannot be a word. */
export const giveInvite = (code) => {
  const clean = cleanInvite(code)
  if (!clean) return false
  access.invite = clean
  access.inviteWrong = false
  writeInvite(storage(), clean)
  return true
}

/**
 * The city answered invite_needed: it asks for the word. When the call showed
 * one, that word is not known (or no longer): it is forgotten, and the next
 * ask says so calmly.
 */
export const inviteRefused = (sent = '') => {
  access.inviteRequired = true
  if (!sent) return
  access.inviteWrong = true
  if (access.invite === sent) {
    access.invite = ''
    forgetInvite(storage())
  }
}

/** A limit or access answer from the city, in its own calm words, or ''. */
export const calmLine = (err) => (err && err.cityCode ? String(err.message || '') : '')

/** The code of a limit or access answer ('city_full', 'slow_down', ...), or ''. */
export const calmCode = (err) => (err && err.cityCode ? String(err.cityCode) : '')

/** The city's code in a response body, when it is one of its calm refusals, or ''. */
export const cityCodeOf = (body) => {
  const code = body && typeof body === 'object' ? body.code : undefined
  return typeof code === 'string' && CITY_CODES.includes(code) ? code : ''
}

/**
 * Note a failed call in the console. A limit or a closed door (a city code:
 * 429, 403, 413) is the city answering as it should, so it is noted quietly
 * (info, one line, no stack); anything else is still an error, as it always was.
 */
export const noteResponseError = (error, con = console) => {
  const code = cityCodeOf(error?.response?.data)
  if (!code) {
    con.error('Response error:', error)
    return
  }
  const status = error?.response?.status
  const method = String(error?.config?.method || '').toUpperCase()
  const url = String(error?.config?.url || '')
  const call = [method, url].filter(Boolean).join(' ')
  con.info(`The city declined${call ? ` ${call}` : ''}: ${code}${status ? ` (${status})` : ''}`)
}
