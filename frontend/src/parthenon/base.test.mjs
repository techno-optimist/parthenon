// Run: cd frontend && node --test src/parthenon/base.test.mjs
//
// Where the city stands on the site: every address the page makes for itself
// goes under the base, once; and no '/media/' or '/api/' address in the
// source escapes the helpers.
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  normalizeBase,
  joinBase,
  joinSrcset,
  resolveApiBase,
  joinApi,
  resolvePublicBuild,
  BASE,
  API_BASE,
  PUBLIC_BUILD,
  withBase,
  withBaseSrcset,
  apiUrl
} from './base.js'

test('a base always starts and ends with a slash', () => {
  assert.equal(normalizeBase(undefined), '/')
  assert.equal(normalizeBase(''), '/')
  assert.equal(normalizeBase('.'), '/')
  assert.equal(normalizeBase('./'), '/')
  assert.equal(normalizeBase('/'), '/')
  assert.equal(normalizeBase('/parthenon'), '/parthenon/')
  assert.equal(normalizeBase('/parthenon/'), '/parthenon/')
  assert.equal(normalizeBase('parthenon'), '/parthenon/')
  assert.equal(normalizeBase(' /parthenon/ '), '/parthenon/')
  assert.equal(normalizeBase('//parthenon//'), '//parthenon//', 'a protocol-relative base is left as it is')
  assert.equal(normalizeBase('/a//b'), '/a/b/')
  assert.equal(normalizeBase('https://cdn.example/app'), 'https://cdn.example/app/')
})

test('at the root, site paths are as they always were', () => {
  assert.equal(joinBase('/', '/media/hero/a.jpg'), '/media/hero/a.jpg')
  assert.equal(joinBase('/', 'media/hero/a.jpg'), '/media/hero/a.jpg')
  assert.equal(joinBase(undefined, '/media/x.mp3'), '/media/x.mp3')
})

test('under a base, a site path goes under it once', () => {
  const base = '/parthenon/'
  assert.equal(joinBase(base, '/media/hero/a.jpg'), '/parthenon/media/hero/a.jpg')
  assert.equal(joinBase(base, 'media/hero/a.jpg'), '/parthenon/media/hero/a.jpg')
  assert.equal(joinBase('/parthenon', '/media/a.jpg'), '/parthenon/media/a.jpg')
  // Already under it: never twice.
  assert.equal(joinBase(base, '/parthenon/media/a.jpg'), '/parthenon/media/a.jpg')
  assert.equal(joinBase(base, joinBase(base, '/media/a.jpg')), '/parthenon/media/a.jpg')
  assert.equal(joinBase(base, '/parthenon'), '/parthenon')
  // A path that only begins with the same letters is not under it.
  assert.equal(joinBase(base, '/parthenon.svg'), '/parthenon/parthenon.svg')
  assert.equal(joinBase(base, '/parthenonx/a.jpg'), '/parthenon/parthenonx/a.jpg')
})

test('full URLs, data:, blob: and nothing are left alone', () => {
  const base = '/parthenon/'
  assert.equal(joinBase(base, 'https://example.com/a.jpg'), 'https://example.com/a.jpg')
  assert.equal(joinBase(base, 'http://localhost:5001/api/x'), 'http://localhost:5001/api/x')
  assert.equal(joinBase(base, '//cdn.example/a.jpg'), '//cdn.example/a.jpg')
  assert.equal(joinBase(base, 'data:image/png;base64,AAAA'), 'data:image/png;base64,AAAA')
  assert.equal(joinBase(base, 'blob:https://x/1'), 'blob:https://x/1')
  assert.equal(joinBase(base, ''), '')
  assert.equal(joinBase(base, null), '')
  assert.equal(joinBase(base, undefined), '')
})

test('every candidate of a srcset goes under the base', () => {
  assert.equal(
    joinSrcset('/parthenon/', '/media/figures/a-560.jpg 560w, /media/figures/a.jpg 832w'),
    '/parthenon/media/figures/a-560.jpg 560w, /parthenon/media/figures/a.jpg 832w'
  )
  assert.equal(joinSrcset('/', '/media/a.jpg 1x,/media/b.jpg 2x'), '/media/a.jpg 1x, /media/b.jpg 2x')
  assert.equal(joinSrcset('/parthenon/', '/media/a.jpg'), '/parthenon/media/a.jpg')
  assert.equal(joinSrcset('/parthenon/', ''), '')
})

test('the API is the local backend at the root, and this origin under a base', () => {
  assert.equal(resolveApiBase({ base: '/' }), 'http://localhost:5001')
  assert.equal(resolveApiBase({}), 'http://localhost:5001')
  assert.equal(resolveApiBase({ base: '/parthenon/' }), '/parthenon')
  assert.equal(resolveApiBase({ base: '/parthenon' }), '/parthenon')
  // An explicit VITE_API_BASE_URL wins; an empty one is this origin.
  assert.equal(resolveApiBase({ explicit: 'http://10.0.0.2:5001/', base: '/' }), 'http://10.0.0.2:5001')
  assert.equal(resolveApiBase({ explicit: '/city', base: '/parthenon/' }), '/city')
  assert.equal(resolveApiBase({ explicit: '', base: '/' }), '')
})

test('a backend-relative asset gets the API base once', () => {
  const film = '/api/parthenon/chronicle/report_53d558ea0a3d/film/film.mp4'
  assert.equal(joinApi('http://localhost:5001', film), `http://localhost:5001${film}`)
  assert.equal(joinApi('/parthenon', film), `/parthenon${film}`)
  assert.equal(joinApi('/parthenon/', film), `/parthenon${film}`)
  // The backend may already write it under the prefix (x-forwarded-prefix): never twice.
  assert.equal(joinApi('/parthenon', `/parthenon${film}`), `/parthenon${film}`)
  assert.equal(joinApi('', film), film)
  assert.equal(joinApi('/parthenon', 'api/x'), '/parthenon/api/x')
  assert.equal(joinApi('/parthenon', 'https://x.example/a.mp4'), 'https://x.example/a.mp4')
  assert.equal(joinApi('/parthenon', ''), '')
  assert.equal(joinApi('/parthenon', null), '')
  // A full-URL API base never swallows a path that merely starts like it.
  assert.equal(joinApi('http://localhost:5001', '/parthenon/x'), 'http://localhost:5001/parthenon/x')
})

test('a build under a base is the public build unless it says otherwise', () => {
  assert.equal(resolvePublicBuild({ base: '/' }), false)
  assert.equal(resolvePublicBuild({ base: '/parthenon/' }), true)
  assert.equal(resolvePublicBuild({ flag: '0', base: '/parthenon/' }), false)
  assert.equal(resolvePublicBuild({ flag: '1', base: '/' }), true)
  assert.equal(resolvePublicBuild({ flag: 'true', base: '/' }), true)
  assert.equal(resolvePublicBuild({ flag: '', base: '/' }), false)
})

test('outside Vite (node) the page stands at the root, as on the owner\'s machine', () => {
  assert.equal(BASE, '/')
  assert.equal(API_BASE, 'http://localhost:5001')
  assert.equal(PUBLIC_BUILD, false)
  assert.equal(withBase('/media/voices/hero.mp3'), '/media/voices/hero.mp3')
  assert.equal(withBaseSrcset('/media/a.jpg 1x'), '/media/a.jpg 1x')
  assert.equal(apiUrl('/api/parthenon/voice/x.mp3'), 'http://localhost:5001/api/parthenon/voice/x.mp3')
})

// ---- No address escapes the helpers ----
// Every '/media/…' or '/api/…' string in the source is made through withBase
// (or withBaseSrcset), or is an API client path (src/api, relative to the
// client's base URL, itself under the base). A url() in a component's <style>
// is rebased by Vite at build time (scripts/check-base.mjs checks the build).

const here = dirname(fileURLToPath(import.meta.url))
const SRC = join(here, '..')
const ROOT = join(SRC, '..')

const walk = (dir, out = []) => {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) walk(path, out)
    else if (/\.(js|mjs|vue|html|css)$/.test(name)) out.push(path)
  }
  return out
}

const ADDRESS = /["'`(]\/(media|api)\//g
const COMMENT = /^\s*(\/\/|\*|\/\*|<!--)/

const escapes = (file) => {
  const rel = relative(ROOT, file)
  const text = readFileSync(file, 'utf8')
  const found = []
  let inStyle = false
  text.split('\n').forEach((line, i) => {
    if (/<style\b/.test(line)) inStyle = true
    if (/<\/style>/.test(line)) {
      inStyle = false
      return
    }
    if (inStyle || COMMENT.test(line)) return
    for (const m of line.matchAll(ADDRESS)) {
      const kind = m[1]
      // An API client path, relative to the client's base URL.
      if (kind === 'api' && rel.startsWith('src/api/')) continue
      const helper = Math.max(line.lastIndexOf('withBase(', m.index), line.lastIndexOf('withBaseSrcset(', m.index))
      if (helper >= 0) continue
      found.push(`${rel}:${i + 1}: ${line.trim()}`)
    }
  })
  return found
}

test('no /media/ or /api/ address in the source escapes the helpers', () => {
  const files = [...walk(SRC), join(ROOT, 'index.html')].filter(
    (f) => !/\.test\.mjs$/.test(f) && !f.endsWith(join('parthenon', 'base.js'))
  )
  assert.ok(files.length > 50, 'the source was read')
  const found = files.flatMap(escapes)
  assert.deepEqual(found, [], `addresses outside withBase:\n${found.join('\n')}`)
})

test('the page asks nothing of another host but the fonts', () => {
  const files = walk(SRC).filter((f) => !/\.test\.mjs$/.test(f) && !f.includes(`${join('parthenon', 'arrivals')}`))
  const hosts = new Set()
  for (const file of [...files, join(ROOT, 'index.html')]) {
    const text = readFileSync(file, 'utf8')
    // Addresses the page loads from (src, href of a stylesheet or preconnect, fetch, url()).
    for (const m of text.matchAll(/(?:src=|fetch\(|url\(|rel="(?:stylesheet|preconnect)"\s+href=|href=)["'`]?(https?:\/\/[^/"'`)\s]+)/g)) {
      hosts.add(new URL(m[1]).host)
    }
    for (const m of text.matchAll(/['"`](https:\/\/fonts\.[a-z]+\.com)/g)) hosts.add(new URL(m[1]).host)
  }
  // Links a visitor may follow (MiroFish, Zep) are not loads; only these hosts are loaded from.
  const loaded = [...hosts].filter((h) => !['github.com', 'app.getzep.com', 'www.w3.org'].includes(h))
  for (const host of loaded) assert.ok(['fonts.googleapis.com', 'fonts.gstatic.com'].includes(host), host)
})

test('no inline event handler is written into the page', () => {
  const found = []
  for (const file of [...walk(SRC), join(ROOT, 'index.html')].filter((f) => !/\.test\.mjs$/.test(f))) {
    const text = readFileSync(file, 'utf8')
    // An on*= attribute in markup, or one set through setAttribute / innerHTML strings.
    for (const m of text.matchAll(/<[a-z][^>]*\s(on[a-z]+)=["']/g)) found.push(`${relative(ROOT, file)}: ${m[1]}`)
    for (const m of text.matchAll(/setAttribute\(\s*['"](on[a-z]+)['"]/g)) found.push(`${relative(ROOT, file)}: ${m[1]}`)
  }
  assert.deepEqual(found, [])
})

test('the router, the API client and the build all stand under the one base', () => {
  const read = (rel) => readFileSync(join(ROOT, rel), 'utf8')
  assert.match(read('src/router/index.js'), /createWebHistory\(BASE\)/)
  assert.match(read('src/api/index.js'), /baseURL: API_BASE/)
  assert.match(read('vite.config.js'), /process\.env\.VITE_BASE/)
  assert.match(read('vite.config.js'), /^\s*base,$/m)
  assert.match(read('index.html'), /var base = '%BASE_URL%'/)
})
