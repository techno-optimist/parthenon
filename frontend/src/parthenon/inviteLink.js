// A link that carries the word (?invite=CODE): taken in once, as the page
// first loads, and cleared from the address bar before the router reads it,
// so the word is never left in the history, a bookmark or a shared link.
// Imported first by main.js (and by access.js, which keeps the word).
import { inviteInLink, writeInvite } from './invite.js'

const take = () => {
  if (typeof window === 'undefined' || !window.location) return ''
  const { code, url } = inviteInLink(window.location.href)
  if (!url) return ''
  try {
    window.history.replaceState(window.history.state, '', url)
  } catch {
    // The address could not be changed; the word is still kept.
  }
  if (code) {
    try {
      writeInvite(window.localStorage, code)
    } catch {
      // Storage refused (a private window): the word lives for this visit.
    }
  }
  return code
}

/** The word this page load was given by its link, or ''. */
export const linkedInvite = take()
