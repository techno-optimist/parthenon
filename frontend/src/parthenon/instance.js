// The city's account of itself, read once and shared: whether it is on the
// public steps, what it can make there, and how many gatherings are left today.
import { getInstanceStatus } from '../api/parthenon.js'
import { access, applyStatus } from './access.js'

let pending = null
let askedAt = 0

/**
 * Read GET /api/parthenon/status into the shared access store. Resolves the
 * status data, or null when the city did not answer (then the next call asks
 * again). With maxAge (ms) a reading older than that is taken afresh (the
 * limits change through the day); without it the first reading is shared.
 */
export const loadInstance = ({ maxAge = Infinity } = {}) => {
  if (pending && Date.now() - askedAt <= maxAge) return pending
  askedAt = Date.now()
  const call = getInstanceStatus()
    .then((res) => {
      const data = res?.data || null
      applyStatus(data)
      return data
    })
    .catch(() => {
      if (pending === call) pending = null
      return null
    })
  pending = call
  return call
}

export { access }
