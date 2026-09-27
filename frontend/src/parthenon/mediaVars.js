// The stills the styles paint with, under the page's base.
//
// A url('/media/...') written in a style is left at the site's root unless
// Vite finds the file at build time, and under /parthenon/ that is a picture
// the site does not have. So the styles never name a still: they paint with a
// custom property (background: var(--p-still-symposium, none) ...), and the
// page sets each one on :root from withBase as it starts (main.js), so the
// same build stands at '/' and under '/parthenon/'.
import { withBase } from './base.js'

export const MEDIA_VARS = [
  ['--p-still-agora-night', withBase('/media/acts/square/agora-ancient-night-1920.jpg')],
  ['--p-still-symposium', withBase('/media/acts/symposium.jpg')],
  ['--p-still-chronicle', withBase('/media/acts/chronicle.jpg')],
  ['--p-still-steps-band', withBase('/media/figures/steps-band-1920.jpg')]
]

/** A path as a CSS url() value; a quote, a backslash or a line break can never close it early. */
export const cssUrl = (path) => `url("${String(path ?? '').replace(/["\\\r\n]/g, '')}")`

/** Set every still on an element (the document's root), through the CSSOM (allowed under the site's CSP). */
export const applyMediaVars = (el, vars = MEDIA_VARS) => {
  if (!el || !el.style || typeof el.style.setProperty !== 'function') return
  for (const [name, path] of vars) el.style.setProperty(name, cssUrl(path))
}
