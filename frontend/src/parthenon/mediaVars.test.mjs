// Run: cd frontend && node --test src/parthenon/mediaVars.test.mjs
//
// The stills the styles paint with come from custom properties set under the
// page's base; no style names a still (or anything of this site) by a
// root address that would escape '/parthenon/'.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import { MEDIA_VARS, applyMediaVars, cssUrl } from './mediaVars.js'
import { joinBase } from './base.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..')
const SRC = join(ROOT, 'src')

const walk = (dir, out = []) => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) walk(path, out)
    else if (/\.(vue|css)$/.test(name)) out.push(path)
  }
  return out
}

// The style text of a file: a .css whole, a .vue's <style> blocks.
const stylesOf = (file) => {
  const text = readFileSync(file, 'utf8')
  if (file.endsWith('.css')) return text
  return [...text.matchAll(/<style\b[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join('\n')
}

test('every still is a site path under /media, set through withBase', () => {
  assert.ok(MEDIA_VARS.length >= 4)
  const names = new Set()
  for (const [name, path] of MEDIA_VARS) {
    assert.match(name, /^--p-still-[a-z0-9-]+$/)
    assert.ok(!names.has(name), `${name} once`)
    names.add(name)
    // Outside Vite the base is '/', so the path is the site path itself.
    assert.match(path, /^\/media\/[a-z0-9/._-]+\.(jpg|webp|png)$/)
    assert.ok(statSync(join(ROOT, 'public', path)).isFile(), `${path} is in public/`)
  }
  // Under the public base the same still stands under it.
  assert.equal(joinBase('/parthenon/', MEDIA_VARS[0][1]), `/parthenon${MEDIA_VARS[0][1]}`)
})

test('a path becomes a url() no quote, backslash or line break can close early', () => {
  assert.equal(cssUrl('/parthenon/media/acts/symposium.jpg'), 'url("/parthenon/media/acts/symposium.jpg")')
  assert.equal(cssUrl('/a") x("b\\\n'), 'url("/a) x(b")')
  assert.equal(cssUrl(null), 'url("")')
})

test('the stills are set on the root through the CSSOM', () => {
  const set = {}
  const el = { style: { setProperty: (k, v) => { set[k] = v } } }
  applyMediaVars(el)
  assert.equal(Object.keys(set).length, MEDIA_VARS.length)
  for (const [name, path] of MEDIA_VARS) assert.equal(set[name], `url("${path}")`)
  applyMediaVars(null)
  applyMediaVars({})
  applyMediaVars(el, [['--p-still-x', '/parthenon/media/x.jpg']])
  assert.equal(set['--p-still-x'], 'url("/parthenon/media/x.jpg")')
})

test('no style names a still, or anything of this site, by a root or relative address', () => {
  const found = []
  for (const file of walk(SRC)) {
    const css = stylesOf(file)
    for (const m of css.matchAll(/url\(\s*["']?([^"')\s]*)/g)) {
      const target = m[1]
      if (/^(data:|#|%23|var\()/.test(target) || target === '') continue
      found.push(`${relative(ROOT, file)}: url(${target})`)
    }
  }
  assert.deepEqual(found, [], `styles naming an address:\n${found.join('\n')}`)
})

test('every still a style paints with is one the page sets', () => {
  const known = new Set(MEDIA_VARS.map(([name]) => name))
  const used = new Set()
  for (const file of walk(SRC)) {
    for (const m of stylesOf(file).matchAll(/var\(\s*(--p-still-[a-z0-9-]+)/g)) used.add(m[1])
  }
  assert.ok(used.size >= 4, 'the stills are painted')
  for (const name of used) assert.ok(known.has(name), `${name} is set by mediaVars.js`)
  // And the page sets them as it starts.
  const main = readFileSync(join(SRC, 'main.js'), 'utf8')
  assert.match(main, /applyMediaVars\(document\.documentElement\)/)
})

test('the page takes the word from its link before the router reads the address', () => {
  const main = readFileSync(join(SRC, 'main.js'), 'utf8')
  const imports = [...main.matchAll(/^import .*$/gm)].map((m) => m[0])
  assert.equal(imports[0], "import './parthenon/inviteLink.js'")
  assert.ok(imports.findIndex((l) => l.includes("'./router'")) > 0)
  // The icon stands under the base whether or not the build finds public/.
  assert.match(readFileSync(join(ROOT, 'index.html'), 'utf8'), /rel="icon"[^>]*href="%BASE_URL%parthenon\.svg"/)
})
