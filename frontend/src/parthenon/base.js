// Where the city stands on the site. On the owner's own machine the steps are
// at the root ('/'); on projectforty2.ai they are at '/parthenon/'. Every
// address the page makes for itself (the paintings, the footage, the voices,
// the sound, the API and the files the backend hands back) comes through here,
// so the same build works under either.
//
// The build sets the base with VITE_BASE (vite.config.js), which Vite hands to
// the page as import.meta.env.BASE_URL. Outside Vite (the node tests) there is
// no import.meta.env and the base is '/'.

const ENV = (() => {
  try {
    return import.meta.env || {}
  } catch {
    return {}
  }
})()

// A scheme (https:, data:, blob:) or a protocol-relative '//host' is left alone.
const FOREIGN = /^(?:[a-z][a-z0-9+.-]*:|\/\/)/i

/** '/parthenon' -> '/parthenon/'; '', '.', './' and nothing -> '/'. */
export const normalizeBase = (base) => {
  let b = String(base ?? '').trim()
  if (!b || b === '.' || b === './') return '/'
  if (FOREIGN.test(b)) return b.endsWith('/') ? b : `${b}/`
  if (!b.startsWith('/')) b = `/${b}`
  if (!b.endsWith('/')) b = `${b}/`
  return b.replace(/\/{2,}/g, '/')
}

/**
 * A site path under the base: joinBase('/parthenon/', '/media/x.jpg') is
 * '/parthenon/media/x.jpg'. A path already under the base, a full URL, a
 * data: or blob: URL comes back as it was; nothing gives ''.
 */
export const joinBase = (base, path) => {
  if (path === null || path === undefined || path === '') return ''
  const p = String(path)
  if (FOREIGN.test(p)) return p
  const b = normalizeBase(base)
  if (b === '/') return p.startsWith('/') ? p : `/${p}`
  const root = b.slice(0, -1)
  if (p === root || p.startsWith(b)) return p
  return p.startsWith('/') ? `${root}${p}` : `${b}${p}`
}

/** Every candidate of a srcset under the base: 'a.jpg 560w, b.jpg 832w'. */
export const joinSrcset = (base, srcset) =>
  String(srcset ?? '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [url, ...rest] = part.split(/\s+/)
      return [joinBase(base, url), ...rest].join(' ')
    })
    .join(', ')

/**
 * Where the API is. An explicit VITE_API_BASE_URL wins (an empty one means
 * this origin). Otherwise a page under a base asks its own origin under that
 * base ('/parthenon'), and a page at the root asks the local backend, as it
 * always has ('http://localhost:5001').
 */
export const resolveApiBase = ({ explicit, base } = {}) => {
  if (typeof explicit === 'string') return explicit.trim().replace(/\/+$/, '')
  const b = normalizeBase(base)
  return b === '/' ? 'http://localhost:5001' : b.slice(0, -1)
}

/**
 * A backend-relative path the API hands back ('/api/parthenon/chronicle/<id>/film/film.mp4')
 * as an address the page can load: the API base in front, once. A path the
 * backend already wrote under the base, or a full URL, comes back as it was.
 */
export const joinApi = (apiBase, path) => {
  if (!path || typeof path !== 'string') return ''
  if (FOREIGN.test(path)) return path
  const base = String(apiBase || '').replace(/\/+$/, '')
  const p = path.startsWith('/') ? path : `/${path}`
  if (!base) return p
  // A base that is a path on this origin ('/parthenon'): a path already under it stays.
  if (base.startsWith('/') && (p === base || p.startsWith(`${base}/`))) return p
  return `${base}${p}`
}

/** The public build: the base is not the root, unless VITE_PARTHENON_PUBLIC says otherwise. */
export const resolvePublicBuild = ({ flag, base } = {}) => {
  if (flag !== undefined && flag !== null && String(flag).trim() !== '') return /^(1|true|yes|on)$/i.test(String(flag).trim())
  return normalizeBase(base) !== '/'
}

export const BASE = normalizeBase(ENV.BASE_URL)
export const API_BASE = resolveApiBase({ explicit: ENV.VITE_API_BASE_URL, base: BASE })
export const PUBLIC_BUILD = resolvePublicBuild({ flag: ENV.VITE_PARTHENON_PUBLIC, base: BASE })

/** A site path ('/media/...') as this page must ask for it. */
export const withBase = (path) => joinBase(BASE, path)
/** A srcset of site paths, each under the base. */
export const withBaseSrcset = (srcset) => joinSrcset(BASE, srcset)
/** A backend-relative path ('/api/...') as this page must ask for it. */
export const apiUrl = (path) => joinApi(API_BASE, path)
