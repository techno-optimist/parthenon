// Check a built page stands wholly under its base: every address it makes for
// itself (the page's own files, the media, url() in the styles) begins with
// the base, and nothing is left at the site's root.
//
// Run after a build:
//   VITE_BASE=/parthenon/ npx vite build --outDir dist
//   node scripts/check-base.mjs dist /parthenon/
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

const [dist = 'dist', rawBase = '/parthenon/'] = process.argv.slice(2)
const base = rawBase.endsWith('/') ? rawBase : `${rawBase}/`
const problems = []

const walk = (dir, out = []) => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) walk(path, out)
    else out.push(path)
  }
  return out
}

// index.html: the page's scripts, styles and icon under the base; no env left unreplaced.
const html = readFileSync(join(dist, 'index.html'), 'utf8')
if (html.includes('%BASE_URL%')) problems.push('index.html: %BASE_URL% was not replaced')
if (!html.includes(`var base = '${base}'`)) problems.push(`index.html: the hero preload does not know the base ${base}`)
for (const m of html.matchAll(/\s(?:src|href)="(\/[^"]*)"/g)) {
  if (!m[1].startsWith(base)) problems.push(`index.html: ${m[1]} is not under ${base}`)
}
for (const m of html.matchAll(/["'](\/(?:media|api|assets)\/[^"']*)["']/g)) {
  if (!m[1].startsWith(base)) problems.push(`index.html: ${m[1]} is not under ${base}`)
}

const assets = walk(join(dist, 'assets'))

// Styles: every url() of this site under the base, and no still named by a
// relative path (it would resolve against the stylesheet, not the base). The
// stills the styles paint with come through custom properties the page sets
// from withBase (src/parthenon/mediaVars.js): each one a style uses must be
// set by a script.
const stills = new Set()
for (const file of assets.filter((f) => f.endsWith('.css'))) {
  const css = readFileSync(file, 'utf8')
  for (const m of css.matchAll(/url\(\s*["']?(\/[^"')]*)/g)) {
    if (!m[1].startsWith(base) && !m[1].startsWith('//')) problems.push(`${file}: url(${m[1]}) is not under ${base}`)
  }
  for (const m of css.matchAll(/url\(\s*["']?((?:\.{1,2}\/)*media\/[^"')]*)/g)) {
    problems.push(`${file}: url(${m[1]}) names a still by a relative path`)
  }
  for (const m of css.matchAll(/var\(\s*(--p-still-[a-z0-9-]+)/g)) stills.add(`${file}|${m[1]}`)
}

// Scripts: the base is built in, and every media path is handed straight to a
// function (withBase), never left as a bare literal. The minifier may fold
// f(c ? a : f(b)) into f(c ? a : b), so a branch of a conditional counts as
// handed over; a property ({ scene: '/media/…' }) or an assignment does not.
const scripts = assets.filter((f) => f.endsWith('.js'))
const js = scripts.map((f) => [f, readFileSync(f, 'utf8')])
if (!js.some(([, text]) => text.includes(`BASE_URL:"${base}"`))) problems.push(`no script carries BASE_URL "${base}"`)
for (const [file, text] of js) {
  for (const m of text.matchAll(/["'`]\/media\//g)) {
    const before = text[m.index - 1]
    const branch = before === '?' || (before === ':' && /["'`)]/.test(text[m.index - 2]))
    if (before !== '(' && !branch) problems.push(`${file}: a bare media path near …${text.slice(Math.max(0, m.index - 40), m.index + 40)}…`)
  }
  if (/\bnew Function\(|\beval\(/.test(text)) problems.push(`${file}: eval or new Function (not allowed by the site's CSP)`)
}
for (const entry of stills) {
  const [file, name] = entry.split('|')
  if (!js.some(([, text]) => text.includes(`"${name}"`) || text.includes(`'${name}'`))) {
    problems.push(`${file}: var(${name}) is painted but no script sets it`)
  }
}

if (problems.length) {
  console.error(`The build at ${dist} does not stand wholly under ${base}:`)
  for (const p of problems) console.error(`  ${p}`)
  process.exit(1)
}
console.log(`The build at ${dist} stands under ${base}: index.html, ${assets.filter((f) => f.endsWith('.css')).length} stylesheets, ${scripts.length} scripts checked.`)
