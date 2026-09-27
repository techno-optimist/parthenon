<template>
  <div class="chronicle-stage">
    <!-- One polite live region for the act: the Scribe's progress, in words. -->
    <p class="visually-hidden" role="status" aria-live="polite">{{ statusLine }}</p>

    <div class="chronicle" :class="{ 'has-margin': wide && chapters.length }">
      <!-- The contents, in the margin on wide screens -->
      <nav
        v-if="wide && chapters.length"
        class="contents contents--margin"
        :aria-label="$t('parthenon.chronicle.chaptersNav')"
      >
        <span class="p-eyebrow contents-label">{{ $t('parthenon.chronicle.contents') }}</span>
        <ol class="contents-list">
          <li
            v-for="ch in chapters"
            :key="ch.index"
            class="contents-item"
            :class="[`is-${ch.state}`, { current: ch.index === activeChapter }]"
          >
            <button
              type="button"
              class="contents-link"
              :disabled="ch.state === 'pending'"
              :aria-current="ch.index === activeChapter ? 'true' : undefined"
              @click="goToChapter(ch.index)"
            >
              <span class="contents-num">{{ numeral(ch.index) }}</span>
              <span class="contents-title" :lang="ch.lang">{{ ch.title }}</span>
              <span v-if="ch.state !== 'done'" class="contents-note">{{ stateNote(ch.state) }}</span>
            </button>
          </li>
        </ol>
      </nav>

      <div class="folio">
        <!-- The film, once made, announced at the top like a marquee; the film itself is the coda. -->
        <aside v-if="marquee" class="marquee" :aria-labelledby="ids.marquee">
          <div class="marquee-poster" aria-hidden="true">
            <img v-if="marquee.poster" :src="marquee.poster" alt="" decoding="async" />
          </div>
          <div class="marquee-shade" aria-hidden="true"></div>
          <div class="marquee-copy">
            <p class="p-eyebrow marquee-eyebrow">{{ $t('parthenon.chronicle.marquee.eyebrow') }}</p>
            <p :id="ids.marquee" class="marquee-title" :lang="textLang(marquee.title)">{{ marquee.title }}</p>
            <p v-if="marquee.logline" class="marquee-logline" :lang="textLang(marquee.logline)">{{ marquee.logline }}</p>
            <div class="marquee-actions">
              <button type="button" class="p-button" @click="watchFilm">
                <svg class="play" viewBox="0 0 12 14" width="11" height="13" aria-hidden="true"><path d="M1 1.2v11.6L11 7z" fill="currentColor" /></svg>
                <span>{{ $t('parthenon.chronicle.marquee.watch') }}</span>
              </button>
              <span v-if="marquee.runtime" class="marquee-runtime">{{ $t('parthenon.chronicle.marquee.runtime', { time: marquee.runtime }) }}</span>
            </div>
          </div>
        </aside>

        <!-- The page itself: parchment held up in the dark -->
        <!-- An address with no Chronicle behind it -->
        <article v-if="missing" class="p-paper page page--missing" :aria-labelledby="ids.title">
          <header class="title-page">
            <div class="title-head">
              <p class="p-eyebrow">{{ $t('history.title') }}</p>
              <h1 :id="ids.title" class="title">{{ $t('parthenon.chronicle.notFound') }}</h1>
              <p class="standfirst">{{ $t('parthenon.chronicle.notFoundBody') }}</p>
            </div>
            <div class="title-rest">
              <div class="p-meander rule" aria-hidden="true"></div>
              <div class="actions">
                <router-link :to="{ name: 'Chronicles' }" class="p-button">{{ $t('parthenon.chronicle.toChronicles') }}</router-link>
                <router-link to="/" class="p-button secondary">{{ $t('parthenon.hearing.empty.back') }}</router-link>
              </div>
            </div>
          </header>
        </article>

        <article v-else class="p-paper page" :aria-labelledby="ids.title" :lang="pageLang">
          <header class="title-page" :class="plate ? `has-plate plate-${plate.kind}` : ''">
            <div class="title-head">
              <p class="p-eyebrow" :lang="uiLang">{{ $t('parthenon.chronicle.eyebrow') }}</p>
              <h1 :id="ids.title" class="title">{{ title }}</h1>
              <p v-if="standfirst" class="standfirst">{{ standfirst }}</p>
            </div>

            <!-- Who took the steps, or the stage the city gathered on -->
            <figure v-if="plate" class="plate" :class="`is-${plate.kind}`" :lang="uiLang">
              <div class="plate-frame">
                <img :src="plate.src" :alt="plate.name || ''" decoding="async" />
              </div>
              <figcaption v-if="plate.name" class="plate-caption">
                <span v-if="plate.greek" class="plate-greek" aria-hidden="true">{{ plate.greek }}</span>
                <span class="plate-name">{{ plate.name }}</span>
                <span v-if="plate.caption" class="plate-note">{{ plate.caption }}</span>
              </figcaption>
            </figure>

            <div class="title-rest">
              <div class="p-meander rule" aria-hidden="true"></div>
              <div v-if="question" class="question">
                <span class="p-eyebrow question-label" :lang="uiLang">{{ $t('parthenon.chronicle.questionLabel') }}</span>
                <p class="question-text" :lang="textLang(question)">{{ question }}</p>
              </div>
              <p v-if="dateLine" class="date" :lang="uiLang">{{ dateLine }}</p>

              <div v-if="isComplete" class="actions" :lang="uiLang">
                <button type="button" class="p-button" @click="goToInteraction">
                  {{ $t('parthenon.chronicle.enterSymposium') }}
                </button>
                <button v-if="mayFilm" type="button" class="p-button secondary" @click="revealFilm">
                  {{ $t('parthenon.chronicle.filmIt') }}
                </button>
              </div>
            </div>
          </header>

          <!-- The film's first scene, held up after the title page -->
          <figure v-if="frontispiece" class="shot-plate is-frontispiece">
            <div class="shot-frame">
              <img :src="frontispiece.src" :alt="frontispiece.narration" loading="lazy" decoding="async" width="1280" height="720" />
            </div>
            <figcaption class="shot-caption">
              <span class="shot-from" :lang="uiLang">{{ $t('parthenon.chronicle.plates.fromFilm', { title: filmTitle }) }}</span>
              <span class="shot-line" :lang="textLang(frontispiece.narration)">{{ frontispiece.narration }}</span>
            </figcaption>
          </figure>

          <!-- Trouble: the Scribe could not finish -->
          <section v-if="trouble" class="trouble" role="alert" :lang="uiLang">
            <p class="trouble-title">{{ $t('parthenon.chronicle.troubleTitle') }}</p>
            <details class="trouble-why">
              <summary>{{ $t('parthenon.chronicle.troubleWhy') }}</summary>
              <p>{{ trouble }}</p>
            </details>
          </section>

          <!-- While the Scribe writes: one line, in words, and a breathing ink line -->
          <div v-else-if="!isComplete" class="scribe-wait" :lang="uiLang">
            <p class="scribe-status">
              <span class="ink-line" aria-hidden="true"></span>
              <span>{{ statusLine }}</span>
            </p>
            <p class="wait-note">
              <i18n-t keypath="parthenon.chronicle.waitNote" tag="span" scope="global">
                <template #shelf>
                  <router-link :to="{ name: 'Chronicles' }">{{ $t('parthenon.chronicle.shelf') }}</router-link>
                </template>
              </i18n-t>
            </p>
          </div>

          <!-- The contents, on the page, when there is no margin for them -->
          <nav
            v-if="!wide && chapters.length"
            :lang="uiLang"
            class="contents contents--inline"
            :aria-label="$t('parthenon.chronicle.chaptersNav')"
          >
            <span class="p-eyebrow contents-label">{{ $t('parthenon.chronicle.contents') }}</span>
            <ol class="contents-list">
              <li
                v-for="ch in chapters"
                :key="ch.index"
                class="contents-item"
                :class="[`is-${ch.state}`, { current: ch.index === activeChapter }]"
              >
                <button
                  type="button"
                  class="contents-link"
                  :disabled="ch.state === 'pending'"
                  :aria-current="ch.index === activeChapter ? 'true' : undefined"
                  @click="goToChapter(ch.index)"
                >
                  <span class="contents-num">{{ numeral(ch.index) }}</span>
                  <span class="contents-title" :lang="ch.lang">{{ ch.title }}</span>
                  <span v-if="ch.state !== 'done'" class="contents-note">{{ stateNote(ch.state) }}</span>
                </button>
              </li>
            </ol>
          </nav>

          <!-- The chapters, as they are finished -->
          <section
            v-for="ch in visibleChapters"
            :key="ch.index"
            :id="chapterId(ch.index)"
            class="chapter"
            :class="[`is-${ch.state}`, { 'has-notes': ch.state === 'done' && (ch.cast.length || ch.notes.length), 'has-plates': ch.plates.length }]"
            :aria-labelledby="chapterId(ch.index) + '-title'"
            :lang="ch.lang"
          >
            <header class="chapter-head">
              <span class="p-eyebrow chapter-num" :lang="uiLang">{{ $t('parthenon.chronicle.chapter', { n: numeral(ch.index) }) }}</span>
              <h2 :id="chapterId(ch.index) + '-title'" class="chapter-title" tabindex="-1">{{ ch.title }}</h2>
            </header>

            <!-- A scene of the film opens the chapter -->
            <figure v-if="ch.plates[0]" class="shot-plate is-opening">
              <div class="shot-frame">
                <img :src="ch.plates[0].src" :alt="ch.plates[0].narration" loading="lazy" decoding="async" width="1280" height="720" />
              </div>
              <figcaption class="shot-caption">
                <span class="shot-line" :lang="textLang(ch.plates[0].narration)">{{ ch.plates[0].narration }}</span>
              </figcaption>
            </figure>

            <!-- The margin: the faces this chapter names, and how the Scribe found it.
                 On narrow screens its parts fall into the column: faces under the
                 heading, the note after the prose. -->
            <div v-if="ch.state === 'done' && (ch.cast.length || ch.notes.length)" class="chapter-margin" :lang="uiLang">
              <div
                v-if="ch.cast.length"
                class="cast"
                role="group"
                :aria-label="$t('parthenon.chronicle.cast.label', { n: numeral(ch.index) })"
              >
                <span class="p-eyebrow cast-label" aria-hidden="true">{{ $t('parthenon.chronicle.cast.title') }}</span>
                <ul class="cast-list">
                  <li v-for="m in castShown(ch)" :key="m.key" class="cast-member">
                    <CitizenCoin
                      :name="m.name"
                      :type="m.type"
                      :portrait="portraitOf(m)"
                      :size="margins ? 'md' : 'sm'"
                    />
                    <span class="cast-name">{{ m.name }}</span>
                  </li>
                </ul>
                <p v-if="ch.cast.length > castShown(ch).length" class="cast-more">{{ castRest(ch) }}</p>
              </div>

              <details v-if="ch.notes.length" class="how-found">
                <summary>
                  <span>{{ $t('parthenon.chronicle.howFound') }}</span>
                  <span class="how-chev" aria-hidden="true"></span>
                </summary>
                <ul class="how-list">
                  <li v-for="(line, i) in ch.notes" :key="i">{{ line }}</li>
                </ul>
              </details>
            </div>

            <div v-if="ch.state === 'done'" class="chapter-body" v-html="ch.htmlA"></div>
            <!-- And another at its middle -->
            <figure v-if="ch.state === 'done' && ch.plates[1]" class="shot-plate is-mid">
              <div class="shot-frame">
                <img :src="ch.plates[1].src" :alt="ch.plates[1].narration" loading="lazy" decoding="async" width="1280" height="720" />
              </div>
              <figcaption class="shot-caption">
                <span class="shot-line" :lang="textLang(ch.plates[1].narration)">{{ ch.plates[1].narration }}</span>
              </figcaption>
            </figure>
            <div v-if="ch.state === 'done' && ch.htmlB" class="chapter-body chapter-body--rest" v-html="ch.htmlB"></div>
            <div v-if="ch.state !== 'done'" class="chapter-writing" :lang="uiLang">
              <p class="scribe-status">
                <span class="ink-line" aria-hidden="true"></span>
                <span>{{ $t('parthenon.chronicle.writingThis') }}</span>
              </p>
              <p v-if="ch.latest" class="chapter-latest">{{ ch.latest }}</p>
            </div>
          </section>

          <!-- Colophon: the Scribe sets down her pen -->
          <footer v-if="isComplete" class="colophon" :lang="uiLang">
            <div class="p-meander rule" aria-hidden="true"></div>
            <p class="colophon-line">{{ $t('parthenon.chronicle.colophon') }}</p>
            <button type="button" class="p-button" @click="goToInteraction">
              {{ $t('parthenon.chronicle.enterSymposium') }}
            </button>
          </footer>

          <!-- The film, as the epilogue of the document -->
          <ChronicleFilm v-if="!trouble" ref="filmPanel" :lang="uiLang" :report-id="reportId" :ready="isComplete" />
        </article>
      </div>
    </div>
  </div>
</template>

<script setup>
// Act Δ΄: the Chronicle, written by the Scribe of Athens. The engine writes
// chapter by chapter; the page reveals each one as it is finished and says,
// in one line, where the Scribe is. The engine's own account goes to the
// ledger through add-log.
//
// The Chronicle reads as one book: a title page with the face of the speaker
// (or the painting of the stage), the faces of the citizens each chapter names
// in its margin, a note on how the Scribe found each chapter in plain words,
// and the film as the epilogue, announced at the top once it is made.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRef, useId, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getAgentLog, getConsoleLog, getReport } from '../api/report'
import { getSimulationConfig, getSimulationProfiles } from '../api/simulation'
import { filmAssetUrl, getChronicleFilm } from '../api/parthenon'
import {
  citizenName,
  entityTypeName,
  roleFamily,
  stripIds,
  cityWords as speakInCity,
  smartQuotes,
  textLang
} from '../parthenon/vocabulary.js'
import { useCitizenPortraits } from '../parthenon/portraits.js'
import ChronicleFilm from './ChronicleFilm.vue'
import { canControl, featureOn } from '../parthenon/access.js'
import CitizenCoin from './CitizenCoin.vue'

// Chapters are numbered the Greek way, with the keraia, as the Symposium's
// drawer numbers them. (A shared helper in vocabulary.js is requested.)
const GREEK = ['Α΄', 'Β΄', 'Γ΄', 'Δ΄', 'Ε΄', 'Ϛ΄', 'Ζ΄', 'Η΄', 'Θ΄', 'Ι΄', 'ΙΑ΄', 'ΙΒ΄', 'ΙΓ΄', 'ΙΔ΄', 'ΙΕ΄', 'ΙϚ΄', 'ΙΖ΄', 'ΙΗ΄', 'ΙΘ΄', 'Κ΄']
const greekNumeral = (n) => GREEK[n - 1] || String(n)

const router = useRouter()
const { t, tm, rt, locale } = useI18n()

const props = defineProps({
  reportId: String,
  simulationId: String,
  report: { type: Object, default: null },
  loadError: { type: String, default: '' },
  // The image beside the title: { kind: portrait|scene|act, src, name, greek, caption }
  plate: { type: Object, default: null },
  // No Chronicle at this address (a mistyped or forgotten link)
  missing: { type: Boolean, default: false }
})

const emit = defineEmits(['add-log', 'update-status', 'update-title'])

const uid = String(useId() || 'ch').replace(/[^A-Za-z0-9_-]/g, '')
const ids = { title: `${uid}-chronicle-title`, marquee: `${uid}-chronicle-marquee` }
const chapterId = (n) => `${uid}-chapter-${n}`

// Chinese counts its chapters in its own figures; everyone else reads Greek.
const numeral = (n) => (locale.value === 'zh' ? String(n) : greekNumeral(n))

// State from the Scribe's log
const reportOutline = ref(null)
const currentSectionIndex = ref(null)
const generatedSections = ref({})
// What the Scribe did for each chapter: [{ tool, params, iteration, digest }]
const stepsBySection = ref({})
const isComplete = ref(false)
const planningStarted = ref(false)
const agentLogLine = ref(0)
const consoleLogLine = ref(0)
// The Scribe's own word that she could not finish, from her log or her record.
const localTrouble = ref('')
let lastRecordCheck = 0

const filmPanel = ref(null)

// The document

// The Scribe's own words, set as a printer would and in the city's words:
// her prose and headings pass through the city's vocabulary ("agents" are
// citizens, "the platforms" the Agora and the Stoa); the citizens' speech she
// quotes is left as they said it. The record is never changed, only its setting.
const typesetText = (text, lang = textLang(text)) => {
  let out = speakInCity(String(text || ''), lang)
  if (lang !== 'zh') out = smartQuotes(out)
  return out
}
const keepEdges = (text, fn) => {
  const lead = text.match(/^\s*/)[0]
  const tail = text.match(/\s*$/)[0]
  const core = text.slice(lead.length, text.length - tail.length)
  return core ? lead + fn(core) + tail : text
}
// A paragraph, a quotation or a list item in another language than its
// chapter says so, so a screen reader changes voice for it.
const markLanguages = (html, lang) =>
  html.replace(/<(p|blockquote|li)( class="[^"]*"[^>]*)>([\s\S]*?)<\/\1>/g, (m, tag, attrs, inner) => {
    const own = textLang(inner.replace(/<[^>]+>/g, ''))
    return own !== lang ? `<${tag}${attrs} lang="${own}">${inner}</${tag}>` : m
  })

const typeset = (html, lang) => markLanguages(typesetParts(html, lang), lang)
const typesetParts = (html, lang) => {
  let inQuote = 0
  let inCode = 0
  return html
    .split(/(<[^>]+>)/g)
    .map((part) => {
      if (part.startsWith('<')) {
        const m = /^<(\/?)(blockquote|pre|code)\b/i.exec(part)
        if (m) {
          const step = m[1] ? -1 : 1
          if (m[2].toLowerCase() === 'blockquote') inQuote = Math.max(0, inQuote + step)
          else inCode = Math.max(0, inCode + step)
        }
        return part
      }
      if (!part || inCode) return part
      let text = part
      if (!inQuote) text = keepEdges(text, (x) => speakInCity(x, lang))
      if (lang !== 'zh') text = smartQuotes(text)
      return text
    })
    .join('')
}

const title = computed(() => (reportOutline.value?.title ? typesetText(reportOutline.value.title) : t('parthenon.chronicle.untitled')))
const standfirst = computed(() => typesetText(reportOutline.value?.summary || ''))
// The Chronicle's own title names the browser tab, once the Scribe has given one.
watch(
  () => (props.missing || !reportOutline.value?.title ? '' : title.value),
  (name) => emit('update-title', name),
  { immediate: true }
)

// The page is read in the Chronicle's own language; the city's labels on it
// in the visitor's.
const uiLang = computed(() => (String(locale.value).startsWith('zh') ? 'zh' : 'en'))
const pageLang = computed(() => {
  const sample = `${reportOutline.value?.title || ''} ${reportOutline.value?.summary || ''} ${Object.values(generatedSections.value)[0] || ''}`.trim()
  return sample ? textLang(sample.slice(0, 3000)) : uiLang.value
})
const question = computed(() => props.report?.simulation_requirement || '')

const dateLine = computed(() => {
  const finished = isComplete.value && props.report?.completed_at
  const raw = finished ? props.report.completed_at : props.report?.created_at
  if (!raw) return ''
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return ''
  const tag = locale.value === 'zh' ? 'zh-CN' : 'en-GB'
  let text = ''
  try {
    text = new Intl.DateTimeFormat(tag, { day: 'numeric', month: 'long', year: 'numeric' }).format(date)
  } catch {
    text = date.toDateString()
  }
  return t(finished ? 'parthenon.chronicle.setDownOn' : 'parthenon.chronicle.begunOn', { date: text })
})

const trouble = computed(() => {
  if (props.missing) return t('parthenon.chronicle.notFound')
  if (props.loadError) return props.loadError
  if (localTrouble.value) return localTrouble.value
  const r = props.report
  if (r && (r.status === 'failed' || r.error)) return stripIds(r.error) || t('parthenon.chronicle.troubleFallback')
  return ''
})

// The citizens of this gathering, for the faces in the margin.

const citizens = ref([]) // [{ key, id, name, type }]
let citizensFor = null

const nameKey = (name) =>
  String(name || '').normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()

const loadCitizens = async (simulationId) => {
  citizensFor = simulationId || null
  citizens.value = []
  if (!simulationId) return
  const [profilesRes, configRes] = await Promise.allSettled([
    getSimulationProfiles(simulationId),
    getSimulationConfig(simulationId)
  ])
  if (citizensFor !== simulationId) return
  const configs = configRes.status === 'fulfilled' ? configRes.value?.data?.agent_configs || [] : []
  const profiles = profilesRes.status === 'fulfilled' ? profilesRes.value?.data?.profiles || [] : []
  const typeById = new Map()
  const typeByName = new Map()
  for (const c of configs) {
    if (c?.agent_id !== undefined && c?.agent_id !== null) typeById.set(String(c.agent_id), c.entity_type || '')
    if (c?.entity_name) typeByName.set(nameKey(c.entity_name), c.entity_type || '')
  }
  const list = []
  const seen = new Set()
  const add = (id, name, type) => {
    const key = nameKey(name)
    if (!key || seen.has(key)) return
    seen.add(key)
    list.push({ key, id: id === undefined || id === null ? '' : String(id), name, type: type || '' })
  }
  profiles.forEach((p, i) => {
    const id = p?.user_id ?? p?.agent_id ?? i
    const name = citizenName(p?.name, p?.username)
    add(id, name, typeById.get(String(id)) ?? typeByName.get(nameKey(name)) ?? '')
  })
  configs.forEach((c) => add(c?.agent_id, citizenName(c?.entity_name), c?.entity_type))
  citizens.value = list
}

watch(() => props.simulationId, loadCitizens, { immediate: true })

const portraits = useCitizenPortraits(toRef(props, 'simulationId'))
const portraitOf = (m) => portraits.portraitFor(m.name) || (m.id !== '' ? portraits.portraitFor(m.id) : null) || ''

// Finding citizens in the Scribe's prose. A name is found whole; a person's
// first or family name alone counts too when no one else in the city shares it.
// Latin names must stand as words; names in other scripts are found as written.
const LETTER = 'A-Za-z0-9\\u00C0-\\u024F'
const HONORIFIC = /^(the|dr\.?|father|mother|mr\.?|mrs\.?|ms\.?|saint|st\.?|sister|brother)\s+/i
const GENERIC_TAIL = /\s+(campaign|association|cooperative|co-operative|coalition|movement|society|committee|collective)$/i
const COMMON_WORDS = new Set(['the', 'and', 'for', 'city', 'island', 'people', 'council', 'court', 'school', 'young', 'old', 'new', 'saint'])
const escapeRe = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

const matchers = computed(() => {
  const list = citizens.value
  const bare = (name) => name.replace(HONORIFIC, '').trim()
  const tokenCount = new Map()
  for (const c of list) {
    for (const tok of new Set(bare(c.name).split(/\s+/))) tokenCount.set(tok, (tokenCount.get(tok) || 0) + 1)
  }
  return list.map((c) => {
    const aliases = new Set([c.name.trim()])
    const plain = bare(c.name)
    if (plain.length >= 3) aliases.add(plain)
    const trimmed = plain.replace(GENERIC_TAIL, '')
    if (trimmed !== plain && trimmed.split(/\s+/).length >= 2) aliases.add(trimmed)
    const words = plain.split(/\s+/)
    const properName = words.length >= 2 && words.length <= 3 && words.every((w) => /^\p{Lu}/u.test(w))
    if (properName && roleFamily(c.type) === 'people') {
      for (const w of words) {
        if (w.length >= 4 && tokenCount.get(w) === 1 && !COMMON_WORDS.has(w.toLowerCase())) aliases.add(w)
      }
    }
    const patterns = [...aliases].map((alias) => {
      const body = escapeRe(alias).replace(/\s+/g, '\\s+')
      const latin = !/[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]/.test(alias)
      const source = latin ? `(?<![${LETTER}])${body}(?![${LETTER}])` : body
      // One word is found as written (Sand, not sand); several are found in any case.
      return new RegExp(source, /\s/.test(alias) ? 'giu' : 'gu')
    })
    return { citizen: c, patterns }
  })
})

// How often a text names a citizen, and where first. "Anneke Visser" is one
// mention, not one for the whole name and another for "Anneke".
const mentionsOf = (source, patterns) => {
  const spans = []
  for (const re of patterns) {
    for (const m of source.matchAll(re)) spans.push([m.index, m.index + m[0].length])
  }
  spans.sort((a, b) => a[0] - b[0] || b[1] - a[1])
  let count = 0
  let reach = -1
  for (const [start, end] of spans) {
    if (start < reach) continue
    count += 1
    reach = end
  }
  return { count, first: spans.length ? spans[0][0] : -1 }
}

// The citizens a text names: the most named first, then in the order named.
const citizensIn = (text) => {
  const found = []
  const source = String(text || '')
  if (!source) return found
  for (const { citizen, patterns } of matchers.value) {
    const { count, first } = mentionsOf(source, patterns)
    if (count) found.push({ count, first, citizen })
  }
  return found.sort((a, b) => b.count - a.count || a.first - b.first).map((f) => f.citizen)
}

const castCache = new Map()
const castOf = (content) => {
  const key = content
  const cached = castCache.get(key)
  if (cached && cached.matchers === matchers.value) return cached.cast
  const cast = citizensIn(content)
  castCache.set(key, { matchers: matchers.value, cast })
  return cast
}

// The margin holds ten faces, a tablet's row eight, a phone's six.
const castLimit = computed(() => (margins.value ? 10 : phone.value ? 6 : 8))
const castShown = (ch) => ch.cast.slice(0, castLimit.value)
const listFormat = (items) => {
  const tag = locale.value === 'zh' ? 'zh-CN' : 'en-GB'
  try {
    return new Intl.ListFormat(tag, { style: 'long', type: 'conjunction' }).format(items)
  } catch {
    return items.join(', ')
  }
}
// The rest are named in a line; past five, the line counts them instead.
const castRest = (ch) => {
  const rest = ch.cast.slice(castLimit.value).map((m) => m.name)
  if (rest.length <= 5) return t('parthenon.chronicle.cast.more', { names: listFormat(rest) })
  const n = rest.length - 4
  return t('parthenon.chronicle.cast.moreCount', { names: rest.slice(0, 4).join(locale.value === 'zh' ? '、' : ', '), n }, n)
}

// How the Scribe found each chapter, in plain words, from her working log.

// The engine's words for what she searched, turned into the city's.
const cityWords = (text) =>
  scrub(text)
    .replace(/\bTwitter\b/g, 'the Agora')
    .replace(/\bReddit\b/g, 'the Stoa')
    .replace(/\bsimulated\s+/gi, '')
    .replace(/\bsimulations?\b/gi, 'gathering')
    .replace(/\bgraph\b/gi, 'Web')
    .replace(/\bthe\s+the\b/gi, 'the')
    .replace(/\s{2,}/g, ' ')
    .trim()

// A search, shortened to what it was about. A string of bare keywords is no
// topic a reader could follow, so it is left out.
const PROSE_WORDS = /\b(the|a|an|of|and|for|in|on|to|with|about|between|before|after|from|over|during|against)\b/i
const QUESTION_LEAD = /^(how|what|who|whom|whose|why|when|where|which|is|are|was|were|does|do|did|can|could|should|would|will)\s+((does|do|did|is|are|was|were|has|have)\s+)?/i
const TOPIC_WORDS = 9
const topicOf = (query) => {
  let q = cityWords(query).replace(/[“”"]/g, '').replace(/\s+/g, ' ').trim()
  if (!q) return ''
  q = q.replace(QUESTION_LEAD, '')
  let head = q.split(/[:?;!]|\s[-–]\s|\.\s/)[0]
  const comma = head.indexOf(', ')
  if (comma > 0 && head.slice(0, comma).split(' ').length >= 3) head = head.slice(0, comma)
  const words = head.trim().split(' ')
  const opening = words.slice(0, TOPIC_WORDS).join(' ')
  if (!PROSE_WORDS.test(opening) && !opening.includes(',')) return ''
  let out = opening.replace(/[.,;:]+$/, '')
  if (words.length > TOPIC_WORDS) out += '…'
  return out
}

// What a result says, in a few numbers. The engine writes these headings in
// Chinese or English; either is read, and anything unread is left out.
const numberAfter = (text, labels) => {
  for (const label of labels) {
    const m = text.match(new RegExp(`${label}[^0-9\\n]{0,16}(\\d+)`, 'i'))
    if (m) return Number(m[1])
  }
  return null
}
const countListUnder = (text, headings) => {
  const m = text.match(new RegExp(`###\\s*(?:${headings.join('|')})[^\\n]*\\n([\\s\\S]*?)(?=\\n###|$)`, 'i'))
  if (!m) return 0
  return (m[1].match(/^\s*\d+\.\s/gm) || []).length
}
const digestResult = (tool, result) => {
  const text = String(result || '')
  const digest = {
    agora: (text.match(/\bTwitter\b|Twitter(?=[\u4e00-\u9fff])/g) || []).length,
    stoa: (text.match(/\bReddit\b|Reddit(?=[\u4e00-\u9fff])/g) || []).length
  }
  if (tool === 'insight_forge') {
    digest.facts = numberAfter(text, ['相关预测事实', 'relevant facts', 'facts'])
    digest.questions = countListUnder(text, ['分析的子问题', 'sub-?questions'])
  } else if (tool === 'panorama_search') {
    digest.facts = numberAfter(text, ['当前有效事实', 'active facts', 'current facts'])
  } else if (tool === 'quick_search') {
    digest.facts = numberAfter(text, ['找到', 'found'])
  } else if (tool === 'interview_agents') {
    const m = text.match(/(?:采访人数|interviewed)[^0-9\n]*(\d+)\s*\/\s*(\d+)/i)
    digest.interviewed = m ? Number(m[1]) : null
    digest.names = [...text.matchAll(/^####\s*(?:采访|interview)\s*#?\s*\d+\s*[:：]\s*(.+)$/gim)]
      .map((x) => citizenName(x[1].trim()))
      .filter(Boolean)
  }
  return digest
}

const numberWord = (n) => {
  const words = tm('parthenon.chronicle.found.numbers')
  if (Array.isArray(words) && Number.isInteger(n) && n >= 0 && n < words.length) {
    const w = words[n]
    return typeof w === 'string' ? w : rt(w)
  }
  return String(n)
}

// A citizen's name as the city knows it, when the engine gave a handle.
const knownName = (name) => {
  const key = nameKey(name)
  const hit = citizens.value.find((c) => c.key === key)
  return hit ? hit.name : name
}

const SEARCHES = new Set(['insight_forge', 'panorama_search', 'quick_search'])
const sum = (steps, field) => steps.reduce((total, s) => total + (Number(s.digest?.[field]) || 0), 0)
const unique = (items) => [...new Set(items.filter(Boolean))]

// One line per kind of work, in the order she first did it, and where the
// words she read were said.
const notesFor = (steps) => {
  const groups = new Map()
  steps.forEach((step, i) => {
    const key = ['insight_forge', 'panorama_search', 'quick_search', 'interview_agents', 'get_graph_statistics', 'get_entities_by_type'].includes(step.tool) ? step.tool : 'other'
    if (!groups.has(key)) groups.set(key, { key, steps: [], last: i })
    const g = groups.get(key)
    g.steps.push(step)
    g.last = i
  })
  const lines = []
  for (const g of groups.values()) {
    const text = lineFor(g.key, g.steps)
    if (text) lines.push({ key: g.key, last: g.last, text })
  }
  const agora = sum(steps, 'agora')
  const stoa = sum(steps, 'stoa')
  if (agora || stoa) {
    const where = agora && stoa ? 'followedBoth' : agora ? 'followedAgora' : 'followedStoa'
    let at = -1
    lines.forEach((l, i) => { if (SEARCHES.has(l.key)) at = i })
    lines.splice(at + 1, 0, { key: 'followed', last: -1, text: t(`parthenon.chronicle.found.${where}`) })
  }
  return lines
}

const lineFor = (key, steps) => {
  const first = steps[0]
  const n = steps.length
  if (key === 'insight_forge') {
    const questions = sum(steps, 'questions')
    const facts = sum(steps, 'facts')
    const topic = topicOf(first.params?.query)
    if (!questions) return topic ? t('parthenon.chronicle.found.deepPlain', { topic }) : t('parthenon.chronicle.found.deepBare')
    if (n > 1 || !topic) return t('parthenon.chronicle.found.deepMany', { q: numberWord(questions), facts }, facts)
    return t('parthenon.chronicle.found.deep', { q: numberWord(questions), facts, topic }, facts)
  }
  if (key === 'panorama_search') {
    const topic = topicOf(first.params?.query)
    if (!topic) return t('parthenon.chronicle.found.wideBare')
    return n > 1
      ? t('parthenon.chronicle.found.wideMore', { topic, n: numberWord(n - 1) }, n - 1)
      : t('parthenon.chronicle.found.wide', { topic })
  }
  if (key === 'quick_search') {
    const names = unique(steps.flatMap((s) => citizensIn(s.params?.query).map((c) => c.name)))
    if (names.length) {
      const shown = names.slice(0, 4)
      const rest = names.length - shown.length
      return rest
        ? t('parthenon.chronicle.found.lookedUpMore', { names: shown.join(', '), n: numberWord(rest) }, rest)
        : t('parthenon.chronicle.found.lookedUp', { names: listFormat(shown) })
    }
    const topic = topicOf(first.params?.query)
    return topic ? t('parthenon.chronicle.found.lookedUpTopic', { topic }) : t('parthenon.chronicle.found.lookedUpBare')
  }
  if (key === 'interview_agents') {
    const answered = steps.filter((s) => s.digest && s.digest.interviewed !== null && s.digest.interviewed !== undefined)
    const interviewed = sum(answered, 'interviewed')
    const asked = steps.reduce((total, s) => total + (Number(s.params?.max_agents) || 0), 0)
    if (!answered.length) return ''
    if (!interviewed) {
      return asked
        ? t('parthenon.chronicle.found.goneHome', { n: numberWord(asked) }, asked)
        : t('parthenon.chronicle.found.goneHomeBare')
    }
    const names = unique(steps.flatMap((s) => s.digest?.names || []).map(knownName))
    return names.length
      ? t('parthenon.chronicle.found.questioned', { n: numberWord(interviewed), names: listFormat(names) }, interviewed)
      : t('parthenon.chronicle.found.questionedBare', { n: numberWord(interviewed) }, interviewed)
  }
  if (key === 'get_graph_statistics') return t('parthenon.chronicle.found.counted')
  if (key === 'get_entities_by_type') {
    const types = unique(steps.map((s) => entityTypeName(s.params?.entity_type)))
    return types.length ? t('parthenon.chronicle.found.roll', { types: listFormat(types) }) : t('parthenon.chronicle.found.rollBare')
  }
  return t('parthenon.chronicle.found.records')
}

// While a chapter is written: what the Scribe is doing now, or last did.
const NOW = {
  insight_forge: 'nowDeep',
  panorama_search: 'nowWide',
  quick_search: 'nowQuick',
  interview_agents: 'nowQuestioning',
  get_graph_statistics: 'nowCounting',
  get_entities_by_type: 'nowRoll'
}
const latestFor = (steps) => {
  if (!steps.length) return ''
  const last = steps[steps.length - 1]
  if (!last.digest) {
    const key = NOW[last.tool] || 'nowRecords'
    const asked = Number(last.params?.max_agents) || 0
    if (key === 'nowQuestioning' && asked) return t('parthenon.chronicle.found.nowQuestioningN', { n: numberWord(asked) }, asked)
    return t(`parthenon.chronicle.found.${key}`)
  }
  const lines = notesFor(steps)
  const index = steps.length - 1
  const line = lines.find((l) => l.last === index)
  return line ? line.text : ''
}

// The film, announced at the top once it is made.

const film = ref(null)
let filmTimer = null
let filmFor = null

const formatRuntime = (seconds) => {
  const total = Math.round(Number(seconds))
  if (!Number.isFinite(total) || total <= 0) return ''
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

const marquee = computed(() => {
  const f = film.value
  if (!f || f.status !== 'completed' || !f.video_url) return null
  return {
    title: f.title ? typesetText(f.title) : t('parthenon.film.untitled'),
    logline: typesetText(f.logline || ''),
    poster: filmAssetUrl(f.poster_url),
    runtime: formatRuntime(f.duration)
  }
})

const clearFilmTimer = () => {
  if (filmTimer) clearTimeout(filmTimer)
  filmTimer = null
}

// A film is read once the Chronicle is written, and read again now and then
// until one is made (quickly while it is being filmed), so the marquee lights
// without a reload.
const checkFilm = async () => {
  clearFilmTimer()
  const reportId = props.reportId
  if (!reportId || !isComplete.value) return
  filmFor = reportId
  if (typeof document !== 'undefined' && document.hidden) {
    filmTimer = setTimeout(checkFilm, 30000)
    return
  }
  try {
    const res = await getChronicleFilm(reportId)
    if (filmFor !== reportId || reportId !== props.reportId) return
    film.value = res?.data || null
  } catch {
    // The marquee waits; the film's own panel at the end says what is wrong.
  }
  if (filmFor !== reportId) return
  const status = film.value?.status
  if (status === 'completed' && film.value?.video_url) return
  filmTimer = setTimeout(checkFilm, status === 'running' ? 12000 : 30000)
}

watch(() => [props.reportId, isComplete.value], ([id, done]) => {
  if (filmFor !== id) film.value = null
  if (id && done) checkFilm()
  else clearFilmTimer()
}, { immediate: true })

// The film's painted scenes, set as plates in the reading: the first after the
// title page, the rest at the chapters' openings and middles in order (at most
// two to a chapter). None while the Chronicle is still being written.
const filmShots = computed(() => {
  const f = film.value
  if (!f || f.status !== 'completed' || !isComplete.value) return []
  return (Array.isArray(f.shots) ? f.shots : [])
    .filter((x) => x && x.status === 'done' && x.thumb_url)
    .sort((a, b) => Number(a.index) - Number(b.index))
    .map((x) => ({ key: x.index, src: filmAssetUrl(x.thumb_url), narration: typesetText(String(x.narration || '').trim()) }))
})
const filmTitle = computed(() => typesetText(film.value?.title || t('parthenon.film.untitled')))
// The film's poster is its first scene, already held up in the marquee above
// the page; the plates begin with the second, unless there is nothing else.
const plateShots = computed(() => {
  const shots = filmShots.value
  return marquee.value?.poster && shots.length > 1 ? shots.slice(1) : shots
})
const frontispiece = computed(() => plateShots.value[0] || null)

const watchFilm = () => {
  filmPanel.value?.reveal()
}
const chapters = computed(() => {
  const sections = reportOutline.value?.sections || []
  return sections.map((section, i) => {
    const index = i + 1
    const content = generatedSections.value[index]
    let state = 'pending'
    if (content) state = 'done'
    else if (currentSectionIndex.value === index) state = 'writing'
    const steps = stepsBySection.value[index] || []
    const lang = textLang(content || section.title || '')
    return {
      index,
      lang,
      title: section.title ? typesetText(section.title, lang) : t('parthenon.chronicle.chapter', { n: index }),
      state,
      html: content ? typeset(renderMarkdown(content), lang) : '',
      cast: content ? castOf(content) : [],
      notes: content ? notesFor(steps).map((n) => n.text) : [],
      latest: state === 'writing' ? latestFor(steps) : ''
    }
  })
})

// A chapter's prose in two parts at the paragraph nearest its middle, so a
// second scene can stand between them.
const splitBody = (html) => {
  const cuts = []
  const re = /<\/p>(?=\s*<(?:p|h[2-5]|ul|ol|blockquote|hr)\b)/g
  let m
  while ((m = re.exec(html))) cuts.push(m.index + m[0].length)
  if (!cuts.length) return [html, '']
  const mid = html.length / 2
  const at = cuts.reduce((best, c) => (Math.abs(c - mid) < Math.abs(best - mid) ? c : best), cuts[0])
  return [html.slice(0, at), html.slice(at)]
}

const platesByChapter = computed(() => {
  const out = new Map()
  const rest = plateShots.value.slice(1)
  const done = chapters.value.filter((ch) => ch.state === 'done')
  if (!rest.length || !done.length) return out
  done.forEach((ch, i) => {
    const from = Math.floor((i * rest.length) / done.length)
    const to = Math.floor(((i + 1) * rest.length) / done.length)
    out.set(ch.index, rest.slice(from, Math.min(to, from + 2)))
  })
  return out
})

const visibleChapters = computed(() =>
  chapters.value
    .filter((ch) => ch.state !== 'pending')
    .map((ch) => {
      const plates = ch.state === 'done' ? platesByChapter.value.get(ch.index) || [] : []
      const [htmlA, htmlB] = plates.length > 1 ? splitBody(ch.html) : [ch.html, '']
      return { ...ch, plates, htmlA, htmlB }
    })
)

const totalSections = computed(() => chapters.value.length)
const completedSections = computed(() => chapters.value.filter((ch) => ch.state === 'done').length)

const statusLine = computed(() => {
  if (props.missing) return t('parthenon.chronicle.notFound')
  if (trouble.value) return t('parthenon.chronicle.troubleTitle')
  if (isComplete.value) return t('parthenon.chronicle.complete')
  if (!reportOutline.value) {
    return planningStarted.value ? t('parthenon.chronicle.planning') : t('parthenon.chronicle.reading')
  }
  const writing = chapters.value.find((ch) => ch.state === 'writing')
  const n = writing ? writing.index : Math.min(completedSections.value + 1, totalSections.value)
  if (completedSections.value >= totalSections.value) return t('parthenon.chronicle.finishing')
  return t('parthenon.chronicle.writing', { n, total: totalSections.value })
})

const stateNote = (state) =>
  state === 'writing' ? t('parthenon.chronicle.beingWritten') : t('parthenon.chronicle.toCome')

// Navigation

const goToInteraction = () => {
  if (props.reportId) router.push({ name: 'Interaction', params: { reportId: props.reportId } })
}

// Filming comes only where the film makers can work, and for the one who began it (on the public steps).
const mayFilm = computed(() => featureOn('film') && canControl(props.reportId))

const revealFilm = () => {
  filmPanel.value?.reveal()
}

const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

const goToChapter = (n) => {
  const el = document.getElementById(chapterId(n))
  if (!el) return
  el.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' })
  const heading = el.querySelector('.chapter-title')
  heading?.focus({ preventScroll: true })
}

// Which chapter the reader is in, for the contents.
const activeChapter = ref(null)
let scrollTicking = false
const updateActiveChapter = () => {
  scrollTicking = false
  const line = 160
  let current = null
  for (const ch of visibleChapters.value) {
    const el = document.getElementById(chapterId(ch.index))
    if (!el) continue
    if (el.getBoundingClientRect().top <= line) current = ch.index
  }
  activeChapter.value = current
}
const onScroll = () => {
  if (scrollTicking) return
  scrollTicking = true
  requestAnimationFrame(updateActiveChapter)
}

// Wide screens carry the contents in the margin.
const WIDE = '(min-width: 1200px)'
const wideQuery = typeof window !== 'undefined' ? window.matchMedia(WIDE) : null
const wide = ref(wideQuery ? wideQuery.matches : false)
const onWide = (e) => { wide.value = e.matches }

// Wider still, each chapter keeps a margin of its own for faces and notes.
const MARGINS = '(min-width: 1280px)'
const marginsQuery = typeof window !== 'undefined' ? window.matchMedia(MARGINS) : null
const margins = ref(marginsQuery ? marginsQuery.matches : false)
const onMargins = (e) => { margins.value = e.matches }

const PHONE = '(max-width: 899px)'
const phoneQuery = typeof window !== 'undefined' ? window.matchMedia(PHONE) : null
const phone = ref(phoneQuery ? phoneQuery.matches : false)
const onPhone = (e) => { phone.value = e.matches }

// Markdown, the Scribe's, into the page's HTML.

const escapeText = (text) => String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;')

const renderMarkdown = (content) => {
  if (!content) return ''

  let text = escapeText(stripIds(content)).trim()
  // The chapter title is set by the page; a stray bold marker sometimes leads.
  text = text.replace(/^[ \t]*\*\*[ \t]*\n+/, '')
  text = text.replace(/^##\s+.+\n+/, '')
  text = text.replace(/^[ \t]*\*\*[ \t]*\n+/, '')

  let html = text.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')

  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h5">$1</h5>')
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  // A paragraph that is only bold is a sub-heading.
  html = html.replace(/^\*\*([^*\n]+?)\*\*\s*$/gm, '<h3 class="md-h3">$1</h3>')

  html = html.replace(/^> ?(.*)$/gm, '<blockquote class="md-quote">$1</blockquote>')
  html = html.replace(/<\/blockquote>\n<blockquote class="md-quote">/g, '<br>')

  html = html.replace(/^(\s*)[-*] (.+)$/gm, (match, indent, body) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-li" data-level="${level}">${body}</li>`
  })
  html = html.replace(/^(\s*)(\d+)\. (.+)$/gm, (match, indent, num, body) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-oli" data-level="${level}">${body}</li>`
  })
  html = html.replace(/(<li class="md-li"[^>]*>.*?<\/li>\s*)+/g, '<ul class="md-ul">$&</ul>')
  html = html.replace(/(<li class="md-oli"[^>]*>.*?<\/li>\s*)+/g, '<ol class="md-ol">$&</ol>')
  html = html.replace(/<\/li>\s+<li/g, '</li><li')
  html = html.replace(/<ul class="md-ul">\s+/g, '<ul class="md-ul">')
  html = html.replace(/<ol class="md-ol">\s+/g, '<ol class="md-ol">')
  html = html.replace(/\s+<\/ul>/g, '</ul>')
  html = html.replace(/\s+<\/ol>/g, '</ol>')

  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(^|[^*\w])\*([^*\n]+?)\*(?=[^*\w]|$)/gm, '$1<em>$2</em>')
  html = html.replace(/(^|[^\w])_([^_\n]+?)_(?=[^\w]|$)/gm, '$1<em>$2</em>')

  html = html.replace(/^---$/gm, '<hr class="md-hr">')

  html = html.replace(/\n\n+/g, '</p><p class="md-p">')
  html = html.replace(/\n/g, '<br>')
  html = '<p class="md-p">' + html + '</p>'

  html = html.replace(/<p class="md-p"><\/p>/g, '')
  html = html.replace(/<p class="md-p">(<h[2-5])/g, '$1')
  html = html.replace(/(<\/h[2-5]>)<\/p>/g, '$1')
  html = html.replace(/<p class="md-p">(<ul|<ol|<blockquote|<pre|<hr)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|<\/pre>|<hr class="md-hr">)<\/p>/g, '$1')
  html = html.replace(/<br>\s*(<ul|<ol|<blockquote)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>)\s*<br>/g, '$1')
  html = html.replace(/<p class="md-p">(<br>\s*)+(<ul|<ol|<blockquote|<pre|<hr)/g, '$2')
  html = html.replace(/(<br>\s*){2,}/g, '<br>')
  html = html.replace(/<p class="md-p">(<br>\s*)+/g, '<p class="md-p">')
  html = html.replace(/(<br>\s*)+<\/p>/g, '</p>')
  html = html.replace(/<p class="md-p"><\/p>/g, '')

  // Ordered lists broken up by prose keep counting.
  const tokens = html.split(/(<ol class="md-ol">(?:<li class="md-oli"[^>]*>[\s\S]*?<\/li>)+<\/ol>)/g)
  let olCounter = 0
  let inSequence = false
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].startsWith('<ol class="md-ol">')) {
      const liCount = (tokens[i].match(/<li class="md-oli"/g) || []).length
      if (liCount === 1) {
        olCounter++
        if (olCounter > 1) tokens[i] = tokens[i].replace('<ol class="md-ol">', `<ol class="md-ol" start="${olCounter}">`)
        inSequence = true
      } else {
        olCounter = 0
        inSequence = false
      }
    } else if (inSequence && /<h[2-5]/.test(tokens[i])) {
      olCounter = 0
      inSequence = false
    }
  }
  return tokens.join('')
}

// The Scribe's log

const applyLog = (log) => {
  if (log.action === 'planning_start' || log.action === 'report_start') planningStarted.value = true

  if (log.action === 'planning_complete' && log.details?.outline) {
    reportOutline.value = log.details.outline
  }
  if (log.action === 'section_start') {
    currentSectionIndex.value = log.section_index
  }
  if (log.action === 'tool_call' && log.section_index) {
    const list = [...(stepsBySection.value[log.section_index] || [])]
    list.push({
      tool: log.details?.tool_name || 'other',
      params: log.details?.parameters || {},
      iteration: log.details?.iteration ?? null,
      digest: null
    })
    stepsBySection.value = { ...stepsBySection.value, [log.section_index]: list }
  }
  if (log.action === 'tool_result' && log.section_index) {
    const list = [...(stepsBySection.value[log.section_index] || [])]
    const tool = log.details?.tool_name || ''
    const iteration = log.details?.iteration ?? null
    for (let i = list.length - 1; i >= 0; i--) {
      const step = list[i]
      if (step.digest || (tool && step.tool !== tool) || (iteration !== null && step.iteration !== null && step.iteration !== iteration)) continue
      list[i] = { ...step, digest: digestResult(step.tool, log.details?.result) }
      break
    }
    stepsBySection.value = { ...stepsBySection.value, [log.section_index]: list }
  }
  if (log.action === 'section_complete' && log.details?.content) {
    generatedSections.value = { ...generatedSections.value, [log.section_index]: log.details.content }
    if (currentSectionIndex.value === log.section_index) currentSectionIndex.value = null
  }
  if (log.action === 'report_complete') {
    isComplete.value = true
    currentSectionIndex.value = null
  }
  // The Scribe says so herself when she cannot finish.
  if (log.action === 'error' && !isComplete.value) {
    const why = scrub(log.details?.error || log.details?.message || '')
    localTrouble.value = why || t('parthenon.chronicle.troubleFallback')
    currentSectionIndex.value = null
  }
}

let agentLogTimer = null
let consoleLogTimer = null
let agentInFlight = false
let consoleInFlight = false

// A Chronicle on its record already: show it whole, and let the log fill in
// how the Scribe found it. A failed record is the Scribe's last word.
const adoptRecord = (r) => {
  if (!r) return
  if (r.status === 'failed' || r.error) {
    if (!isComplete.value) {
      localTrouble.value = scrub(r.error) || t('parthenon.chronicle.troubleFallback')
      currentSectionIndex.value = null
    }
    return
  }
  if (r.status !== 'completed' || isComplete.value) return
  const sections = r.outline?.sections || []
  if (!sections.length) return
  if (!reportOutline.value) {
    reportOutline.value = { title: r.outline.title, summary: r.outline.summary, sections: sections.map((s) => ({ title: s.title })) }
  }
  const done = { ...generatedSections.value }
  sections.forEach((s, i) => { if (s.content && !done[i + 1]) done[i + 1] = s.content })
  generatedSections.value = done
  if (sections.every((s, i) => done[i + 1])) {
    isComplete.value = true
    currentSectionIndex.value = null
    emit('update-status', 'completed')
  }
}

// The log says nothing when the Scribe is stopped from outside, so while she
// is still at work her record is read again now and then.
const RECORD_CHECK_MS = 15000
const checkRecord = async () => {
  const now = Date.now()
  if (now - lastRecordCheck < RECORD_CHECK_MS) return
  lastRecordCheck = now
  const reportId = props.reportId
  try {
    const res = await getReport(reportId)
    if (reportId !== props.reportId) return
    if (res.success && res.data) adoptRecord(res.data)
  } catch (err) {
    console.warn('Could not read the Chronicle\'s record:', err)
  }
}

const fetchAgentLog = async () => {
  if (!props.reportId || agentInFlight) return
  agentInFlight = true
  try {
    const res = await getAgentLog(props.reportId, agentLogLine.value)
    if (res.success && res.data) {
      const newLogs = res.data.logs || []
      const wasComplete = isComplete.value
      newLogs.forEach(applyLog)
      agentLogLine.value = res.data.from_line + newLogs.length
      if (isComplete.value && !wasComplete) emit('update-status', 'completed')
      if (isComplete.value && !res.data.has_more) stopAgentPolling()
      if (newLogs.length) nextTick(onScroll)
      if (!isComplete.value && !trouble.value && !res.data.has_more) checkRecord()
    }
  } catch (err) {
    console.warn('Failed to fetch the Scribe\'s log:', err)
  } finally {
    agentInFlight = false
  }
}

// The engine's console lines go to the ledger, with their own times, in the
// city's words. Bookkeeping is dropped; nothing with a hash in it passes.
const CONSOLE_LINE = /^\[(\d{2}:\d{2}:\d{2})\]\s*(INFO|WARNING|WARN|ERROR|DEBUG)\s*:?\s*(.*)$/
const scrub = (text) =>
  stripIds(
    String(text ?? '')
      .replace(/\b[0-9a-f]{8,}\b\.{0,3}/gi, '')
      .replace(/\bgraph(_id)?=\S+/gi, '')
      .replace(/\S+\.(json|csv|md|txt|log)\b/gi, '')
      .replace(/\bLLM\b/g, 'the Scribe')
      .replace(/\bagents?\b/gi, (w) => (w.endsWith('s') ? 'citizens' : 'citizen'))
  )
// A chapter by its title, from the outline the log gave us or from the record.
const chapterOf = (title) => {
  const wanted = String(title).trim()
  const known = chapters.value.find((ch) => ch.title === wanted)
  if (known) return known
  const sections = props.report?.outline?.sections || []
  const i = sections.findIndex((s) => String(s.title || '').trim() === wanted)
  return i >= 0 ? { index: i + 1, title: sections[i].title } : null
}
const chapterLine = (title, withIndex, withoutIndex) => {
  const ch = chapterOf(title)
  return ch
    ? t(withIndex, { n: numeral(ch.index), title: ch.title })
    : t(withoutIndex, { title: scrub(title) })
}
// The tools the Scribe works with, each with a line in the city's words.
const KNOWN_SOURCES = ['insight_forge', 'panorama_search', 'interview_agents', 'quick_search', 'get_graph_statistics', 'get_entities_by_type']
const toolLine = (tool) => {
  const key = KNOWN_SOURCES.includes(tool) ? tool : 'other'
  return t('parthenon.chronicle.ledger.tool', { what: t(`parthenon.chronicle.sources.${key}`) })
}
const LEDGER = [
  // Bookkeeping the city does not need to hear about.
  { re: /^(Report saved|Outline saved|Section saved|Full report assembled|ReportAgent initialized|Report folder deleted)/, drop: true },
  { re: /^Loaded \d+ /, drop: true },
  { re: /^Calling batch interview/, drop: true },
  { re: /^Fetching all (nodes|edges) for graph/, drop: true },
  { re: /^Graph search/, drop: true },
  { re: /^(PanoramaSearch|InsightForge|QuickSearch|InterviewAgents) /, drop: true, unless: /^InsightForge complete/ },
  { re: /^(LLM attempted|search_graph redirected|get_simulation_context redirected)/, drop: true },
  { re: /^Section .+ (round \d+:|: \d+ consecutive conflicts)/, drop: true },
  // What the Scribe did, in order.
  { re: /^Starting report outline planning/, say: () => t('parthenon.chronicle.log.began') },
  { re: /^Fetching simulation context/, say: () => t('parthenon.chronicle.ledger.readQuestion') },
  { re: /^Search complete: found (\d+)/, say: (m) => t('parthenon.chronicle.ledger.found', { n: m[1] }) },
  { re: /^Fetching statistics for graph/, say: () => t('parthenon.chronicle.ledger.counted') },
  { re: /^Fetched (\d+) nodes/, say: (m) => t('parthenon.chronicle.ledger.readNames', { n: m[1] }) },
  { re: /^Fetched (\d+) edges/, say: (m) => t('parthenon.chronicle.ledger.readTies', { n: m[1] }) },
  { re: /^Fetching node detail/, say: () => t('parthenon.chronicle.ledger.readName') },
  { re: /^Outline planning complete: (\d+)/, say: (m) => t('parthenon.chronicle.log.planned', { n: m[1] }) },
  { re: /^ReACT generating section: (.+)$/, say: (m) => chapterLine(m[1], 'parthenon.chronicle.log.chapterBegun', 'parthenon.chronicle.ledger.chapterBegunTitle') },
  { re: /^Executing tool: (\w+)/, say: (m) => toolLine(m[1]) },
  { re: /^Generated (\d+) sub-queries/, say: (m) => t('parthenon.chronicle.ledger.subQuestions', { n: m[1] }) },
  { re: /^InsightForge complete: (\d+) facts, (\d+) entities, (\d+) relationships/, say: (m) => t('parthenon.chronicle.ledger.searchClosed', { facts: m[1], names: m[2], ties: m[3] }) },
  { re: /^Selected (\d+) agents for interview/, say: (m) => t('parthenon.chronicle.ledger.chose', { n: m[1] }) },
  { re: /^Generated (\d+) interview questions/, say: (m) => t('parthenon.chronicle.ledger.questions', { n: m[1] }) },
  { re: /^Interview API returned: (\d+) results/, say: (m) => t(Number(m[1]) > 0 ? 'parthenon.chronicle.ledger.answered' : 'parthenon.chronicle.ledger.noAnswer') },
  { re: /^Interview API (call failed|returned failure|call exception)/, say: () => t('parthenon.chronicle.ledger.interviewFailed') },
  { re: /^Section (.+) reached max iterations/, say: (m) => t('parthenon.chronicle.ledger.ranLong', { title: scrub(m[1]) }) },
  { re: /^Section (.+) iteration \d+: LLM returned None/, say: (m) => t('parthenon.chronicle.ledger.paused', { title: scrub(m[1]) }) },
  { re: /^Section (.+) force-finish/, say: (m) => t('parthenon.chronicle.ledger.chapterFailed', { title: scrub(m[1]) }) },
  { re: /^Section (.+?) (generation complete|missing 'Final Answer:')/, say: (m) => chapterLine(m[1], 'parthenon.chronicle.log.chapterDone', 'parthenon.chronicle.ledger.chapterDoneTitle') },
  { re: /^Report generation complete/, say: () => t('parthenon.chronicle.log.done') },
  { re: /^Report generation failed:?\s*(.*)/, say: (m) => t('parthenon.chronicle.ledger.failed', { error: scrub(m[1]) }) },
  { re: /^Outline planning failed:?\s*(.*)/, say: (m) => t('parthenon.chronicle.ledger.planFailed', { error: scrub(m[1]) }) },
  { re: /^Tool execution failed: \w+, error:?\s*(.*)/, say: (m) => t('parthenon.chronicle.ledger.toolFailed', { error: scrub(m[1]) }) },
  { re: /^Failed to [^:]+:?\s*(.*)/, say: (m) => t('parthenon.chronicle.ledger.snag', { error: scrub(m[1]) }) }
]

const toLedger = (line) => {
  const m = CONSOLE_LINE.exec(String(line))
  const time = m ? m[1] : ''
  const level = m ? m[2] : 'INFO'
  const raw = (m ? m[3] : String(line)).trim()
  for (const rule of LEDGER) {
    if (!rule.re.test(raw)) continue
    if (rule.unless && rule.unless.test(raw)) continue
    if (rule.drop) return null
    const message = rule.say(rule.re.exec(raw))
    return message ? { time, message } : null
  }
  // Unknown lines: warnings are worth a word to the owner; the rest is noise.
  if (level === 'INFO' || level === 'DEBUG') return null
  const message = scrub(raw)
  return message ? { time, message: t('parthenon.chronicle.ledger.trouble', { message }) } : null
}

const fetchConsoleLog = async () => {
  if (!props.reportId || consoleInFlight) return
  consoleInFlight = true
  try {
    const res = await getConsoleLog(props.reportId, consoleLogLine.value)
    if (res.success && res.data) {
      const newLogs = res.data.logs || []
      newLogs.forEach((line) => {
        const entry = toLedger(line)
        if (entry) emit('add-log', entry)
      })
      consoleLogLine.value = res.data.from_line + newLogs.length
      if ((isComplete.value || trouble.value) && !res.data.has_more) stopConsolePolling()
    }
  } catch (err) {
    console.warn('Failed to fetch the engine\'s console:', err)
  } finally {
    consoleInFlight = false
  }
}

const startPolling = () => {
  if (agentLogTimer || consoleLogTimer) return
  lastRecordCheck = Date.now() // the view has just read the record
  // The Scribe's own log first, so the chapters are known before her console
  // lines name them.
  fetchAgentLog().then(fetchConsoleLog)
  agentLogTimer = setInterval(fetchAgentLog, 2000)
  consoleLogTimer = setInterval(fetchConsoleLog, 1500)
}

const stopAgentPolling = () => {
  if (agentLogTimer) {
    clearInterval(agentLogTimer)
    agentLogTimer = null
  }
}

const stopConsolePolling = () => {
  if (consoleLogTimer) {
    clearInterval(consoleLogTimer)
    consoleLogTimer = null
  }
}

const stopPolling = () => {
  stopAgentPolling()
  stopConsolePolling()
}

const resetState = () => {
  reportOutline.value = null
  currentSectionIndex.value = null
  generatedSections.value = {}
  stepsBySection.value = {}
  isComplete.value = false
  planningStarted.value = false
  agentLogLine.value = 0
  consoleLogLine.value = 0
  activeChapter.value = null
  localTrouble.value = ''
  lastRecordCheck = 0
}

watch(() => props.report, (r) => {
  if (r && r.status === 'completed') adoptRecord(r)
}, { immediate: true })

// When the Scribe cannot finish, the polling stops and the Way shows Trouble.
// The console is read once more so her last words reach the ledger.
watch(trouble, (why) => {
  if (why) {
    stopAgentPolling()
    if (consoleLogTimer) {
      fetchConsoleLog().finally(stopConsolePolling)
    }
    emit('update-status', 'error')
  }
}, { immediate: true })

watch(() => props.reportId, (newId) => {
  stopPolling()
  resetState()
  if (newId && !trouble.value) startPolling()
}, { immediate: true })

onMounted(() => {
  wideQuery?.addEventListener('change', onWide)
  marginsQuery?.addEventListener('change', onMargins)
  phoneQuery?.addEventListener('change', onPhone)
  window.addEventListener('scroll', onScroll, { passive: true })
  nextTick(onScroll)
})

onBeforeUnmount(() => {
  stopPolling()
  clearFilmTimer()
  wideQuery?.removeEventListener('change', onWide)
  marginsQuery?.removeEventListener('change', onMargins)
  phoneQuery?.removeEventListener('change', onPhone)
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.chronicle-stage {
  flex: 1;
  width: 100%;
  min-width: 0;
  padding: clamp(24px, 4vw, 56px) var(--p-gutter) 80px;
}

.visually-hidden {
  position: absolute !important;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  clip-path: inset(50%);
  white-space: nowrap;
  border: 0;
}

.chronicle {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  justify-items: center;
  min-width: 0;
}

/* The folio: the film's marquee above the page, the page below */
.folio {
  width: 100%;
  max-width: 58rem;
  min-width: 0;
}

/* The film, announced like a marquee on the night above the page */
.marquee {
  position: relative;
  display: grid;
  align-items: end;
  min-height: clamp(200px, 18vw, 250px);
  margin-bottom: clamp(20px, 3vw, 32px);
  overflow: hidden;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  border-top: 1px solid color-mix(in srgb, var(--p-gold) 55%, transparent);
  box-shadow: var(--p-shadow-2);
  animation: marquee-in 0.9s ease both;
}

.marquee-poster {
  position: absolute;
  inset: 0;
}

.marquee-poster img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 40%;
}

.marquee-shade {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, rgba(11, 14, 19, 0.95) 0%, rgba(11, 14, 19, 0.82) 34%, rgba(11, 14, 19, 0.28) 70%, rgba(11, 14, 19, 0.05) 100%),
    linear-gradient(0deg, rgba(11, 14, 19, 0.55) 0%, transparent 55%);
}

.marquee-copy {
  position: relative;
  max-width: 31rem;
  padding: clamp(22px, 3vw, 34px);
}

.marquee-title {
  margin: 8px 0 0;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  line-height: 1.05;
  color: var(--p-ink);
  text-wrap: balance;
}

.marquee-logline {
  display: -webkit-box;
  margin: 8px 0 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.55;
  color: var(--p-ink-2);
}

.marquee-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 18px;
  margin-top: 18px;
}

.marquee-actions .play {
  flex: 0 0 auto;
}

.marquee-runtime {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

@keyframes marquee-in {
  from { opacity: 0; transform: translateY(-8px); }
  to { opacity: 1; transform: none; }
}

/* The page */
.page {
  width: 100%;
  min-width: 0;
  padding: clamp(36px, 6vw, 84px) clamp(20px, 6vw, 92px) clamp(48px, 6vw, 92px);
  box-shadow: var(--p-shadow-2);
  font-family: var(--p-font-serif);
  font-size: 1.125rem;
  line-height: 1.68;
  overflow-wrap: anywhere;
}

/* Title page */
.title-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas:
    'plate'
    'head'
    'rest';
  max-width: 72ch;
  margin: 0 auto;
}

.title-head { grid-area: head; min-width: 0; }
.title-rest { grid-area: rest; min-width: 0; }

.title {
  margin: 14px 0 0;
  font-family: var(--p-font-display);
  font-size: var(--t-3xl);
  font-weight: 500;
  line-height: 1.04;
  letter-spacing: -0.01em;
  color: var(--p-ink);
  text-wrap: balance;
}

.standfirst {
  margin: 22px 0 0;
  max-width: 44em;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.5;
  color: var(--p-ink-3);
}

/* The plate: the speaker, or the stage, framed on the page */
.plate {
  grid-area: plate;
  margin: 0 0 28px;
  min-width: 0;
  animation: plate-in 0.8s ease both;
}

.plate-frame {
  padding: 6px;
  border: 1px solid var(--p-line-strong);
  background: var(--p-surface);
  box-shadow: 0 14px 30px -18px rgba(31, 26, 22, 0.55);
}

.plate-frame img {
  display: block;
  width: 100%;
  aspect-ratio: 16 / 10;
  object-fit: cover;
  object-position: center 30%;
  filter: saturate(0.92) contrast(1.02);
}

.plate.is-portrait .plate-frame img {
  aspect-ratio: 4 / 3;
  object-position: center 22%;
}

.plate-caption {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 12px;
}

.plate-greek {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  color: var(--p-gold);
}

.plate-name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 500;
  line-height: 1.2;
  color: var(--p-ink);
}

.plate-note {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.45;
  color: var(--p-ink-3);
}

@keyframes plate-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

.rule {
  margin: 32px 0 28px;
  opacity: 0.55;
}

.question-label {
  display: block;
  margin-bottom: 8px;
}

.question-text {
  margin: 0;
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
}

.date {
  margin: 18px 0 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 30px;
}

/* The Scribe's status */
.scribe-status {
  display: flex;
  align-items: center;
  gap: 14px;
  max-width: 72ch;
  margin: 40px auto 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
}

.ink-line {
  flex: 0 0 auto;
  width: 44px;
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--p-gold) 40%, var(--p-gold) 60%, transparent);
  transform-origin: left center;
  animation: ink 2.6s ease-in-out infinite;
}

@keyframes ink {
  0%, 100% { transform: scaleX(0.35); opacity: 0.5; }
  50% { transform: scaleX(1); opacity: 1; }
}

/* Trouble */
.trouble {
  max-width: 72ch;
  margin: 40px auto 0;
  padding: 18px 20px;
  border-left: 2px solid var(--p-error);
  background: var(--p-error-tint);
}

.trouble-title {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  color: var(--p-error);
}

.trouble-why {
  margin-top: 8px;
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  color: var(--p-ink-2);
}

.trouble-why summary {
  cursor: pointer;
  color: var(--p-ink-3);
}

.trouble-why p {
  margin: 8px 0 0;
}

/* Contents */
.contents-label {
  display: block;
  margin-bottom: 12px;
}

.contents-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.contents-link {
  display: grid;
  grid-template-columns: 1.6em minmax(0, 1fr);
  column-gap: 8px;
  align-items: baseline;
  align-content: center;
  width: 100%;
  min-height: 40px;
  padding: 7px 8px 7px 10px;
  border: 0;
  border-left: 2px solid transparent;
  background: transparent;
  color: var(--p-ink-2);
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 500;
  line-height: 1.3;
  text-align: left;
  cursor: pointer;
}

.contents-link:hover {
  color: var(--p-gold);
}

.contents-link:disabled {
  cursor: default;
  color: var(--p-ink-4);
}

.contents-item.current .contents-link {
  border-left-color: var(--p-gold);
  color: var(--p-gold);
}

.contents-num {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  color: var(--p-gold);
}

.contents-link:disabled .contents-num {
  color: var(--p-ink-4);
}

.contents-note {
  grid-column: 2;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-xs);
  color: var(--p-ink-4);
}

.contents--inline {
  max-width: 72ch;
  margin: 40px auto 0;
  padding-top: 28px;
  border-top: 1px solid var(--p-line);
}

/* Chapters. In one column the margin's parts fall into the flow: the faces
   under the heading, the note after the prose. */
.chapter {
  display: flex;
  flex-direction: column;
  max-width: 72ch;
  margin: 56px auto 0;
  scroll-margin-top: calc(var(--p-header-h) + 28px);
}

.chapter + .chapter {
  margin-top: 64px;
  padding-top: 52px;
  border-top: 1px solid var(--p-line);
}

.chapter.is-done {
  animation: arrive 0.7s ease both;
}

@keyframes arrive {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: none; }
}

.chapter-head {
  order: 0;
  margin-bottom: 26px;
}

.chapter-margin {
  display: contents;
}

.shot-plate.is-opening { order: 1; }
.cast { order: 2; }
.chapter-body,
.chapter-writing { order: 3; }
.shot-plate.is-mid { order: 4; }
.chapter-body--rest { order: 5; }
.how-found { order: 6; }

.chapter-num {
  display: block;
}

.chapter-title {
  margin: 10px 0 0;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1.1;
  color: var(--p-ink);
  text-wrap: balance;
}

.chapter-title:focus:not(:focus-visible) {
  outline: none;
}

.chapter-writing .scribe-status {
  margin: 8px 0 0;
  font-size: var(--t-md);
}

.chapter-latest {
  margin: 10px 0 0 58px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
  animation: arrive 0.6s ease both;
}

/* The faces a chapter names */
.cast {
  margin: -8px 0 26px;
}

.cast-label {
  display: block;
  margin-bottom: 10px;
  color: var(--p-ochre-deep);
}

.cast-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
}

.cast-member {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  animation: face-in 0.5s ease both;
}

.cast-member:nth-child(2) { animation-delay: 0.06s; }
.cast-member:nth-child(3) { animation-delay: 0.12s; }
.cast-member:nth-child(4) { animation-delay: 0.18s; }
.cast-member:nth-child(5) { animation-delay: 0.24s; }
.cast-member:nth-child(6) { animation-delay: 0.3s; }
.cast-member:nth-child(n + 7) { animation-delay: 0.36s; }

@keyframes face-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
}

.cast-name {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  line-height: 1.2;
  color: var(--p-ink-2);
}

.cast-more {
  margin: 10px 0 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.45;
  color: var(--p-ink-3);
}

/* The film's scenes, held up in the reading as plates: wider than the
   measure, 16:9, each with the narrator's line beneath in italic. */
.shot-plate {
  --bleed: clamp(0px, 4vw, 56px);
  width: calc(100% + 2 * var(--bleed));
  max-width: none;
  margin: 8px calc(-1 * var(--bleed)) 34px;
  animation: arrive 0.8s ease both;
}

.shot-plate.is-frontispiece {
  --bleed: clamp(0px, 4vw, 72px);
  /* Centred on the page's measure, bleeding past it by the same on each side. */
  position: relative;
  left: 50%;
  translate: -50% 0;
  width: min(calc(100% + 2 * var(--bleed)), calc(72ch + 2 * var(--bleed)));
  margin: 44px 0 12px;
}

.shot-plate.is-mid {
  margin-top: 26px;
}

.shot-frame {
  position: relative;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  background: #0b0e13;
  box-shadow: 0 1px 0 rgba(240, 182, 96, 0.35), 0 18px 40px -18px rgba(11, 14, 19, 0.55);
}

.shot-frame::after {
  content: '';
  position: absolute;
  inset: 0;
  box-shadow: inset 0 0 0 1px rgba(11, 14, 19, 0.25), inset 0 0 60px rgba(11, 14, 19, 0.28);
  pointer-events: none;
}

.shot-frame img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.shot-caption {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 60ch;
  margin: 12px auto 0;
  padding: 0 var(--bleed);
  text-align: center;
}

.shot-from {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ochre-deep);
}

.shot-from:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}

.shot-line {
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: 1.08rem;
  line-height: 1.45;
  color: var(--p-ink-3);
  text-wrap: balance;
}

.shot-line:lang(zh) {
  font-style: normal;
  font-family: var(--p-font-serif);
}

/* The long wait, in time, and leave to go */
.scribe-wait {
  max-width: 72ch;
  margin: 0 auto;
}

.wait-note {
  margin: 10px 0 0 58px;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.wait-note a {
  color: var(--p-ink-2);
  text-decoration: underline;
  text-decoration-color: var(--p-ochre);
  text-underline-offset: 3px;
}

/* Chinese is not set in capitals with inscription tracking. */
.marquee-runtime:lang(zh),
.how-found summary span:lang(zh),
.p-eyebrow:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}

/* A missing Chronicle: one sentence, and the way to the shelf */
.page--missing .title-page {
  border-top: 0;
  padding-top: 0;
}

/* The Scribe's prose */
.chapter-body {
  color: var(--p-ink-2);
  min-width: 0;
}

.chapter-body :deep(p) {
  margin: 0 0 1.15em;
}

.chapter-body :deep(p:last-child) {
  margin-bottom: 0;
}

.chapter-body:not(.chapter-body--rest) :deep(> p:first-of-type)::first-letter {
  float: left;
  margin: 0.08em 0.12em 0 0;
  font-family: var(--p-font-display);
  font-size: 4.4em;
  font-weight: 500;
  line-height: 0.78;
  color: var(--p-terracotta);
}

.chapter-body :deep(h3),
.chapter-body :deep(h4),
.chapter-body :deep(h5) {
  margin: 1.8em 0 0.6em;
  font-family: var(--p-font-display);
  font-weight: 600;
  line-height: 1.2;
  color: var(--p-ink);
}

.chapter-body :deep(h3) { font-size: var(--t-lg); }
.chapter-body :deep(h4) { font-size: var(--t-md); }
.chapter-body :deep(h5) { font-size: var(--t-sm); }

.chapter-body :deep(blockquote) {
  margin: 1.3em 0;
  padding: 2px 0 2px 1.1em;
  border-left: 2px solid var(--p-gold);
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: 1.12em;
  line-height: 1.5;
  color: var(--p-ink);
}

.chapter-body :deep(ul),
.chapter-body :deep(ol) {
  margin: 0 0 1.15em;
  padding-left: 1.4em;
}

.chapter-body :deep(li) {
  margin: 0.3em 0;
}

.chapter-body :deep(li[data-level='1']) { margin-left: 1.2em; }
.chapter-body :deep(li[data-level='2']) { margin-left: 2.4em; }

.chapter-body :deep(strong) {
  font-weight: 600;
  color: var(--p-ink);
}

.chapter-body :deep(hr) {
  height: 1px;
  margin: 2em 0;
  border: 0;
  background: var(--p-line);
}

.chapter-body :deep(code) {
  font-family: var(--p-font-mono);
  font-size: 0.85em;
}

.chapter-body :deep(pre) {
  margin: 0 0 1.15em;
  padding: 12px 14px;
  overflow: auto;
  background: var(--p-surface-2);
  border: 1px solid var(--p-line);
}

/* How the Scribe found this: a margin note, folded */
.how-found {
  margin-top: 28px;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.how-found summary {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-height: 40px;
  padding: 8px 0;
  box-sizing: border-box;
  list-style: none;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ochre-deep);
  cursor: pointer;
}

.how-found summary::-webkit-details-marker {
  display: none;
}

.how-found summary:hover {
  color: var(--p-ink);
}

.how-found summary:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 3px;
}

.how-chev {
  width: 7px;
  height: 7px;
  border-right: 1.5px solid currentColor;
  border-bottom: 1.5px solid currentColor;
  transform: translateY(-2px) rotate(45deg);
  transition: transform 0.2s ease;
}

.how-found[open] .how-chev {
  transform: translateY(2px) rotate(-135deg);
}

.how-list {
  list-style: none;
  margin: 6px 0 0;
  padding: 0 0 0 14px;
  border-left: 1px solid var(--p-line-strong);
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-style: italic;
  line-height: 1.5;
}

/* Colophon */
.colophon {
  max-width: 72ch;
  margin: 64px auto 0;
}

.colophon-line {
  margin: 0 0 22px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
}

/* The film sits at the end of the page at reading measure */
.page :deep(.chronicle-film) {
  max-width: 72ch;
  margin-inline: auto;
}

/* Tablets and up: the plate stands beside the title */
@media (min-width: 900px) {
  .title-page.has-plate {
    --plate-w: clamp(220px, 30vw, 330px);
    grid-template-columns: minmax(0, 1fr) var(--plate-w);
    grid-template-areas:
      'head plate'
      'rest rest';
    column-gap: clamp(28px, 4vw, 52px);
    align-items: start;
    max-width: none;
  }

  .title-page.plate-portrait {
    --plate-w: clamp(190px, 22vw, 244px);
  }

  .title-page.has-plate .plate {
    margin: 6px 0 0;
  }

  .plate.is-portrait .plate-frame img {
    aspect-ratio: 4 / 5;
    object-position: center 20%;
  }

  .plate.is-scene .plate-frame img,
  .plate.is-act .plate-frame img {
    aspect-ratio: 4 / 3;
  }
}

/* Wide screens: the contents stand in the margin */
@media (min-width: 1200px) {
  .chronicle.has-margin {
    grid-template-columns: minmax(180px, 220px) minmax(0, 58rem) minmax(0, 1fr);
    column-gap: 40px;
    justify-items: stretch;
  }

  .contents--margin {
    grid-column: 1;
    position: sticky;
    top: calc(var(--p-header-h) + 36px);
    align-self: start;
    min-width: 0;
    padding-top: clamp(36px, 6vw, 84px);
  }

  .chronicle.has-margin .folio {
    grid-column: 2;
  }
}

/* Wider still: each chapter keeps a margin for its faces and its note */
@media (min-width: 1280px) {
  .folio {
    max-width: 66rem;
  }

  .chronicle.has-margin {
    grid-template-columns: minmax(180px, 1fr) minmax(0, 66rem) minmax(0, 1fr);
  }

  .contents--margin {
    justify-self: end;
    width: min(100%, 240px);
  }

  .title-page.has-plate {
    max-width: none;
  }

  .title-page:not(.has-plate) {
    max-width: none;
  }

  .scribe-status,
  .trouble,
  .contents--inline,
  .colophon {
    max-width: none;
  }

  .page :deep(.chronicle-film) {
    max-width: none;
  }

  .chapter {
    display: grid;
    grid-template-columns: minmax(0, 1fr) clamp(172px, 22%, 212px);
    grid-template-rows: auto auto 1fr;
    column-gap: clamp(32px, 3.4vw, 48px);
    max-width: none;
  }

  .chapter-head,
  .chapter-body,
  .chapter-writing,
  .shot-plate.is-mid {
    grid-column: 1;
  }

  .chapter-head { grid-row: 1; }
  .chapter-body,
  .chapter-writing { grid-row: 2; }
  .shot-plate.is-mid { grid-row: 3; }
  .chapter-body--rest { grid-row: 4; }

  /* With a scene at its opening, the scene spans the page and the rest steps down a row. */
  .chapter.has-plates {
    grid-template-rows: auto auto auto auto 1fr;
  }

  .chapter.has-plates .shot-plate.is-opening {
    grid-column: 1 / -1;
    grid-row: 2;
    width: 100%;
    margin: 4px 0 34px;
  }

  .chapter.has-plates .chapter-body:not(.chapter-body--rest),
  .chapter.has-plates .chapter-writing { grid-row: 3; }
  .chapter.has-plates .shot-plate.is-mid { grid-row: 4; width: 100%; margin: 26px 0 34px; }
  .chapter.has-plates .chapter-body--rest { grid-row: 5; }
  .chapter.has-plates .chapter-margin { grid-row: 3 / span 3; }

  .shot-plate.is-frontispiece {
    left: 0;
    translate: none;
    width: 100%;
    margin-inline: 0;
  }

  .chapter-margin {
    display: block;
    grid-column: 2;
    grid-row: 1 / span 3;
    align-self: start;
    padding: 4px 0 4px 20px;
    border-left: 1px solid var(--p-line);
  }

  .cast {
    margin: 0;
  }

  .cast-list {
    flex-direction: column;
    flex-wrap: nowrap;
    gap: 10px;
  }

  .cast-name {
    font-size: var(--t-sm);
  }

  .how-found {
    margin-top: 22px;
    padding-top: 6px;
    border-top: 1px solid var(--p-line);
    font-size: 0.8125rem;
  }

  .how-list {
    padding-left: 10px;
  }
}

@media (min-width: 1400px) {
  .contents--margin {
    width: min(100%, 250px);
  }
}

/* Phones: the page is the document */
@media (max-width: 899px) {
  .chronicle-stage {
    padding: 20px 16px 72px;
  }

  .marquee {
    display: block;
    min-height: 0;
  }

  .marquee-poster {
    position: relative;
    aspect-ratio: 16 / 9;
  }

  .marquee-shade {
    inset: 0 0 auto 0;
    aspect-ratio: 16 / 9;
    background: linear-gradient(0deg, var(--p-surface) 0%, rgba(17, 21, 28, 0) 45%);
  }

  .marquee-copy {
    max-width: none;
    padding: 4px 20px 22px;
  }

  .marquee-title {
    font-size: var(--t-xl);
  }

  .marquee-actions .p-button {
    flex: 1 1 100%;
  }

  .page {
    padding: 34px 20px 44px;
    font-size: 1.0625rem;
    line-height: 1.62;
  }

  /* The scenes bleed to the paper's edge and never past it: the page keeps
     20px each side here, so a plate reaches out at most as far. */
  .shot-plate,
  .shot-plate.is-frontispiece {
    --bleed: min(4vw, 20px);
  }

  .title {
    font-size: var(--t-2xl);
  }

  .plate {
    margin: -34px -20px 26px;
  }

  .plate-frame {
    padding: 0;
    border: 0;
    border-bottom: 1px solid var(--p-line-strong);
    box-shadow: none;
  }

  .plate-caption {
    padding: 0 20px;
  }

  .chapter-title {
    font-size: var(--t-xl);
  }

  .chapter {
    margin-top: 44px;
  }

  .chapter + .chapter {
    margin-top: 48px;
    padding-top: 40px;
  }

  .actions .p-button {
    flex: 1 1 100%;
  }

  .chapter-body:not(.chapter-body--rest) :deep(> p:first-of-type)::first-letter {
    font-size: 3.8em;
  }

  .cast-list {
    gap: 8px 14px;
  }

  .cast-name {
    font-size: var(--t-sm);
  }
}

@media (prefers-reduced-motion: reduce) {
  .ink-line {
    animation: none;
    transform: none;
    opacity: 1;
  }

  .chapter.is-done,
  .chapter-latest,
  .marquee,
  .plate,
  .shot-plate,
  .cast-member {
    animation: none;
  }

  .how-chev {
    transition: none;
  }
}
</style>
