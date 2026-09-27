<template>
  <div class="hearing">
    <!-- One sentence on where the court is. -->
    <p class="status-line" role="status" aria-live="polite">
      <span class="status-ember" :class="`is-${phaseKey}`" aria-hidden="true"></span>
      <span>{{ statusSentence }}</span>
    </p>

    <!-- Trouble, in voice, with the cause folded away. -->
    <section v-if="error" class="trouble" aria-labelledby="hearing-trouble">
      <h2 id="hearing-trouble" class="trouble-title">{{ $t('parthenon.hearing.trouble.title') }}</h2>
      <p class="trouble-body">{{ $t('parthenon.hearing.trouble.body') }}</p>
      <details class="cause">
        <summary>{{ $t('parthenon.hearing.trouble.cause') }}</summary>
        <p>{{ error }}</p>
      </details>
    </section>

    <!-- An address with no scroll behind it. -->
    <section v-if="notFound" class="empty" aria-labelledby="hearing-empty">
      <h2 id="hearing-empty" class="empty-title">{{ $t('parthenon.hearing.notFound') }}</h2>
      <p class="empty-body">{{ $t('parthenon.hearing.notFoundBody') }}</p>
      <div class="door-row">
        <router-link :to="{ name: 'Chronicles' }" class="p-button">{{ $t('parthenon.hearing.toChronicles') }}</router-link>
        <router-link to="/" class="p-button secondary">{{ $t('parthenon.hearing.empty.back') }}</router-link>
      </div>
    </section>

    <!-- A scroll handed over, then lost to a reload: it can be handed over again. -->
    <section v-else-if="noScroll && recovery" class="empty" aria-labelledby="hearing-empty">
      <h2 id="hearing-empty" class="empty-title">{{ $t('parthenon.hearing.recovery.title') }}</h2>
      <p class="empty-body">{{ recovery.ready ? $t('parthenon.hearing.recovery.body') : $t('parthenon.hearing.recovery.chooseAgain') }}</p>
      <div v-if="recovery.question" class="bema">
        <span class="p-eyebrow">{{ $t('parthenon.hearing.scroll.question') }}</span>
        <p class="bema-question" :lang="textLang(recovery.question)">{{ recovery.question }}</p>
      </div>
      <div class="door-row">
        <button v-if="recovery.ready" type="button" class="p-button" @click="$emit('rehand')">{{ $t('parthenon.hearing.recovery.rehand') }}</button>
        <router-link to="/" class="p-button secondary">{{ $t('parthenon.hearing.empty.back') }}</router-link>
      </div>
    </section>

    <!-- No scroll: the visitor came to the court with empty hands. -->
    <section v-else-if="noScroll" class="empty" aria-labelledby="hearing-empty">
      <h2 id="hearing-empty" class="empty-title">{{ $t('parthenon.hearing.empty.title') }}</h2>
      <p class="empty-body">{{ $t('parthenon.hearing.empty.body') }}</p>
      <router-link to="/" class="p-button secondary">{{ $t('parthenon.hearing.empty.back') }}</router-link>
    </section>

    <template v-else>
      <!-- The philosopher who took the steps keeps the floor at the Hearing. -->
      <section v-if="host" class="host" :aria-label="$t('parthenon.hearing.host.label')">
        <span class="host-coin" aria-hidden="true">
          <img :src="host.portrait" alt="" decoding="async" @error="hostFace = false" v-if="hostFace" />
          <span v-else class="host-letter">{{ host.greek ? host.greek.charAt(0) : host.name.charAt(0) }}</span>
        </span>
        <div class="host-copy">
          <p class="p-eyebrow host-floor">{{ $t('parthenon.hasTheFloor', { name: host.name }) }}</p>
          <blockquote class="host-line" :lang="textLang(host.line)">{{ quoted(host.line) }}</blockquote>
          <button type="button" class="host-hear" @click="hearHost(true)">
            <svg viewBox="0 0 20 20" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
              <path d="M3.5 8v4h3l4 3.5v-11L6.5 8z" stroke-linejoin="round" />
              <path d="M13.5 7.2a4 4 0 0 1 0 5.6M15.6 5a7 7 0 0 1 0 10" stroke-linecap="round" />
            </svg>
            <span>{{ $t('parthenon.hearing.host.hear') }}</span>
          </button>
        </div>
      </section>

      <!-- The scroll, held up in the dark. -->
      <section class="scroll-section" aria-labelledby="hearing-scroll">
        <div class="section-head">
          <span id="hearing-scroll" class="p-eyebrow">{{ $t('parthenon.hearing.scroll.eyebrow') }}</span>
          <span v-if="sourceLine" class="section-note">{{ sourceLine }}</span>
        </div>

        <article class="p-paper parchment" :class="{ folded: isFolded }" :lang="scrollLang">
          <h2 class="parchment-title">{{ scrollTitle }}</h2>
          <p v-if="scrollLede" class="parchment-lede">{{ scrollLede }}</p>

          <div v-if="scrollHtml" class="parchment-body" v-html="scrollHtml"></div>

          <div v-else-if="heard" class="parchment-heard">
            <span class="p-eyebrow">{{ $t('parthenon.hearing.scroll.heard') }}</span>
            <p class="parchment-note">{{ $t('parthenon.hearing.scroll.notKept') }}</p>
            <p class="parchment-prose">{{ heard }}</p>
          </div>

          <p v-else class="parchment-note">{{ $t('parthenon.hearing.scroll.reading') }}</p>

          <div v-if="isFolded" class="parchment-fade" aria-hidden="true"></div>
        </article>

        <button
          v-if="isLong"
          type="button"
          class="p-button ghost small unroll"
          :aria-expanded="unrolled"
          @click="unrolled = !unrolled"
        >
          {{ unrolled ? $t('parthenon.hearing.scroll.fold') : $t('parthenon.hearing.scroll.readWhole') }}
        </button>

        <div v-if="question" class="bema">
          <span class="p-eyebrow">{{ $t('parthenon.hearing.scroll.question') }}</span>
          <p class="bema-question" :lang="textLang(question)">{{ question }}</p>
        </div>
      </section>

      <!-- The names, lighting up as the city takes them in. -->
      <section class="names-section" aria-labelledby="hearing-names">
        <div class="section-head">
          <span id="hearing-names" class="p-eyebrow">{{ $t('parthenon.hearing.names.eyebrow') }}</span>
          <span v-if="names.length" class="section-note">{{ countLine }}</span>
        </div>

        <p v-if="!names.length" class="listening" :class="{ live: currentPhase < 2 }">
          <span class="listening-ember" aria-hidden="true"></span>
          {{ $t('parthenon.hearing.names.listening') }}
        </p>

        <ul v-else class="names" role="list">
          <li
            v-for="n in names"
            :key="n.uuid"
            class="name-item"
            :class="{ open: openName === n.uuid }"
            :style="{ '--i': n.order, '--role': n.color }"
          >
            <button
              type="button"
              class="name-button"
              :aria-expanded="openName === n.uuid"
              :aria-label="$t('parthenon.hearing.names.about', { name: n.name })"
              @click="toggleName(n)"
            >
              <span class="name-ember" aria-hidden="true"></span>
              <span class="name-text">
                <span class="name">{{ n.name }}</span>
                <span class="kind">{{ n.kind || $t('parthenon.hearing.names.spokenOf') }}</span>
              </span>
            </button>
            <p v-if="openName === n.uuid && n.summary" class="name-about" :lang="textLang(n.summary)">{{ n.summary }}</p>
          </li>
        </ul>
      </section>

      <!-- The inscription: who may be named, how they are bound. -->
      <section class="inscription-section" aria-labelledby="hearing-inscription">
        <div class="section-head">
          <span id="hearing-inscription" class="p-eyebrow">{{ $t('parthenon.hearing.inscription.eyebrow') }}</span>
        </div>

        <div class="tablet">
          <p v-if="!kinds.length && !ties.length" class="tablet-waiting">{{ $t('parthenon.hearing.inscription.waiting') }}</p>

          <template v-else>
            <div v-if="kinds.length" class="tablet-part">
              <h3 class="tablet-heading">{{ $t('parthenon.hearing.inscription.kinds') }}</h3>
              <ul class="carved" role="list">
                <li v-for="k in kinds" :key="k.id" class="carved-item" :class="{ open: openKind === k.id }">
                  <button
                    type="button"
                    class="carved-button"
                    :aria-expanded="openKind === k.id"
                    @click="openKind = openKind === k.id ? null : k.id"
                  >
                    <span class="carved-mark" :style="{ '--role': k.color }" aria-hidden="true"></span>
                    <span class="carved-word">{{ k.word }}</span>
                  </button>
                  <div v-if="openKind === k.id" class="carved-detail">
                    <p v-if="k.description">{{ k.description }}</p>
                    <p v-if="k.examples.length" class="carved-examples">
                      <span class="p-eyebrow">{{ $t('parthenon.hearing.inscription.forExample') }}</span>
                      <span>{{ k.examples.join(', ') }}</span>
                    </p>
                  </div>
                </li>
              </ul>
            </div>

            <div v-if="ties.length" class="tablet-part">
              <h3 class="tablet-heading">{{ $t('parthenon.hearing.inscription.ties') }}</h3>
              <ul class="carved" role="list">
                <li v-for="tie in ties" :key="tie.id" class="carved-item" :class="{ open: openTie === tie.id }">
                  <button
                    type="button"
                    class="carved-button"
                    :aria-expanded="openTie === tie.id"
                    @click="openTie = openTie === tie.id ? null : tie.id"
                  >
                    <span class="carved-verb">{{ tie.verb }}</span>
                  </button>
                  <div v-if="openTie === tie.id" class="carved-detail">
                    <p v-if="tie.description">{{ tie.description }}</p>
                    <ul v-if="tie.pairs.length" class="pairs" role="list">
                      <li v-for="(pair, idx) in tie.pairs" :key="idx">
                        <span class="pair-word">{{ pair.from }}</span>
                        <span class="pair-verb">{{ tie.verb }}</span>
                        <span class="pair-word">{{ pair.to }}</span>
                      </li>
                    </ul>
                  </div>
                </li>
              </ul>
            </div>
          </template>
        </div>
      </section>

      <!-- The door out of the court: back to the gathering this scroll already
           called, or (the first time) summoning the citizens. -->
      <section class="summon-section" :aria-labelledby="returnTo ? 'hearing-revisit' : undefined">
        <template v-if="returnTo">
          <span id="hearing-revisit" class="p-eyebrow">{{ $t('parthenon.hearing.revisit.eyebrow') }}</span>
          <p class="revisit-line">{{ revisitLine }}</p>
          <div class="door-row">
            <router-link :to="returnTo" class="p-button summon">{{ $t('parthenon.hearing.revisit.return') }}</router-link>
            <button
              type="button"
              class="p-button ghost new-crowd"
              :aria-expanded="confirming ? 'true' : 'false'"
              aria-controls="summon-confirm"
              :disabled="!canSummon"
              @click="confirming = !confirming"
            >{{ $t('parthenon.hearing.revisit.newCrowd') }}</button>
          </div>
          <div v-if="confirming" id="summon-confirm" class="confirm" role="group" aria-labelledby="summon-confirm-title">
            <p id="summon-confirm-title" class="confirm-title">{{ $t('parthenon.hearing.revisit.confirmTitle') }}</p>
            <p class="confirm-body">{{ $t('parthenon.hearing.revisit.confirmBody', { n: crowdSize }) }}</p>
            <div class="door-row">
              <button ref="confirmEl" type="button" class="p-button" :disabled="!canSummon" @click="summonCitizens()">
                <span v-if="summoning" class="summon-ember" aria-hidden="true"></span>
                {{ summoning ? $t('parthenon.hearing.summon.working') : $t('parthenon.hearing.revisit.confirm') }}
              </button>
              <button type="button" class="p-button ghost" @click="confirming = false">{{ $t('parthenon.hearing.revisit.cancel') }}</button>
            </div>
          </div>
        </template>
        <template v-else>
          <button
            type="button"
            class="p-button summon"
            :disabled="!canSummon"
            :aria-describedby="canSummon || currentPhase >= 2 ? undefined : 'summon-when'"
            @click="summonCitizens()"
          >
            <span v-if="summoning" class="summon-ember" aria-hidden="true"></span>
            {{ summoning ? $t('parthenon.hearing.summon.working') : $t('parthenon.hearing.summon.button') }}
          </button>
          <p v-if="currentPhase < 2 && !summoning" id="summon-when" class="summon-when">{{ $t('parthenon.hearing.summon.when') }}</p>
        </template>
        <div v-if="summonError" class="summon-trouble" role="alert">
          <p>{{ $t('parthenon.hearing.summon.failed') }}</p>
          <details class="cause">
            <summary>{{ $t('parthenon.hearing.summon.cause') }}</summary>
            <p>{{ summonError }}</p>
          </details>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
// Act Α΄, the stage: the scroll being read, the names lighting up as the
// city's memory takes them in, the inscription of who may be named and how
// they are bound, and the one door out: summoning the citizens.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { createSimulation } from '../api/simulation'
import {
  entityTypeName,
  roleColorVar,
  tieName,
  isPlatformNode,
  stripIds,
  undash,
  textLang,
  bestGathering,
  gatheringStanding,
  standingRoute
} from '../parthenon/vocabulary.js'
import { sound, speak, voiceUrl } from '../parthenon/sound.js'

const router = useRouter()
const { t, locale } = useI18n()

const props = defineProps({
  currentPhase: { type: Number, default: 0 }, // -1 upload, 0 reading, 1 taking in, 2 known
  projectData: Object,
  graphData: Object,
  // The Web's own count (names without the platform hubs, ties with parallels
  // bundled, chatter apart), computed once by the Hearing and shared with the
  // ledger so the two never disagree with the Web panel.
  web: { type: Object, default: () => ({ names: 0, ties: 0, chatter: 0 }) },
  seedText: { type: String, default: '' },
  seedName: { type: String, default: '' },
  // Where the scroll came from: { kind: 'speaker'|'arrival'|'stage'|'own', name, work, title }
  source: { type: Object, default: null },
  // The philosopher who took the steps: { id, name, greek, line, portrait }
  host: { type: Object, default: null },
  error: { type: String, default: '' },
  noScroll: { type: Boolean, default: false },
  // An address with no scroll behind it
  notFound: { type: Boolean, default: false },
  // A scroll handed over and lost to a reload: { question, files, ready }
  recovery: { type: Object, default: null },
  // The gatherings this scroll has already called (history rows), once read
  gatherings: { type: Array, default: () => [] },
  gatheringsRead: { type: Boolean, default: true },
  // Begun from the steps in this tab: summon the citizens once the court is done
  autoSummon: { type: Boolean, default: false }
})

const emit = defineEmits(['log', 'rehand', 'summoned', 'hold'])

// ---------------------------------------------------------------------------
// Status

const webCounts = computed(() => ({
  names: Number(props.web?.names) || 0,
  ties: Number(props.web?.ties) || 0,
  chatter: Number(props.web?.chatter) || 0
}))

const phaseKey = computed(() => {
  if (props.notFound) return 'lost'
  if (props.error) return 'trouble'
  if (props.noScroll) return 'waiting'
  if (props.currentPhase >= 2) return 'known'
  if (props.currentPhase === 1) return 'takingIn'
  return 'reading'
})

const statusSentence = computed(() => {
  if (phaseKey.value === 'known') {
    if (summoning.value && !props.gatherings.length) return t('parthenon.hearing.status.summoningNow')
    const c = webCounts.value
    const gathered = props.gatherings.length ? 'Gathered' : ''
    return t(`parthenon.hearing.status.known${gathered}${c.chatter ? 'Chatter' : ''}`, c)
  }
  return t(`parthenon.hearing.status.${phaseKey.value}`)
})

const countLine = computed(() => {
  const c = webCounts.value
  return t(c.chatter ? 'parthenon.hearing.names.countChatter' : 'parthenon.hearing.names.count', c)
})

// The scroll's provenance in the city's words; never a file name.
const sourceLine = computed(() => {
  const s = props.source
  if (!s) return ''
  if (s.kind === 'speaker' && s.name) {
    return s.work
      ? t('parthenon.hearing.scroll.fromSpeaker', { name: s.name, work: s.work })
      : t('parthenon.hearing.scroll.fromSpeakerOnly', { name: s.name })
  }
  if (s.kind === 'arrival' && s.title) return t('parthenon.hearing.scroll.fromArrival', { title: s.title })
  if (s.kind === 'stage') return t('parthenon.hearing.scroll.fromStage')
  return t('parthenon.hearing.scroll.fromOwn')
})

// ---------------------------------------------------------------------------
// The scroll

const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const inline = (s) =>
  escapeHtml(s)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')

// The scroll's own title and its first italic line come off the body and are
// set in the parchment's head.
const parsedScroll = computed(() => {
  const raw = String(props.seedText || '').replace(/\r\n?/g, '\n').trim()
  if (!raw) return { title: '', lede: '', html: '' }
  const blocks = raw.split(/\n{2,}/)
  let title = ''
  let lede = ''
  if (blocks[0] && /^# /.test(blocks[0]) && !blocks[0].includes('\n')) title = blocks.shift().slice(2).trim()
  if (blocks[0] && /^\*[^*]+\*$/.test(blocks[0].trim()) && !blocks[0].includes('\n')) lede = blocks.shift().trim().slice(1, -1)
  const html = []
  for (const block of blocks) {
    // The prepared cast lists run on dashes; on the page they read as clauses.
    const lines = block.split('\n').map(undash)
    if (lines.every((l) => l.startsWith('- '))) {
      html.push(`<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join('')}</ul>`)
      continue
    }
    for (const line of lines) {
      if (line.startsWith('### ')) html.push(`<h5>${inline(line.slice(4))}</h5>`)
      else if (line.startsWith('## ')) html.push(`<h4>${inline(line.slice(3))}</h4>`)
      else if (line.startsWith('# ')) html.push(`<h3>${inline(line.slice(2))}</h3>`)
    }
    const prose = lines.filter((l) => !l.startsWith('#')).join(' ')
    if (prose) html.push(`<p>${inline(prose)}</p>`)
  }
  return { title, lede, html: html.join('') }
})

const fileTitle = (name) =>
  String(name || '')
    .replace(/\.[a-z0-9]+$/i, '')
    .replace(/^(arrival|stage)-/i, '')
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())

const scrollTitle = computed(() => parsedScroll.value.title || fileTitle(props.seedName) || t('parthenon.hearing.scroll.untitled'))
// The scroll is read in its own language, whatever the city's.
const scrollLang = computed(() => textLang(`${parsedScroll.value.title} ${props.seedText || heard.value}`.slice(0, 4000)))
const scrollLede = computed(() => parsedScroll.value.lede)
const scrollHtml = computed(() => parsedScroll.value.html)
const heard = computed(() => stripIds(props.projectData?.analysis_summary || ''))
const question = computed(() => props.projectData?.simulation_requirement || '')

const unrolled = ref(false)
const isLong = computed(() => String(props.seedText || '').length > 1600)
const isFolded = computed(() => isLong.value && !unrolled.value)

// ---------------------------------------------------------------------------
// The names

// Each name keeps the order in which it arrived, so a new batch lights up in
// sequence instead of all at once.
const arrivalOrder = new Map()

const names = computed(() => {
  const nodes = Array.isArray(props.graphData?.nodes) ? props.graphData.nodes : []
  const sorted = nodes
    .filter((n) => n && n.name && !isPlatformNode(n.name))
    .slice()
    .sort((a, b) => String(a.created_at || '').localeCompare(String(b.created_at || '')))
  let fresh = 0
  return sorted.map((n) => {
    const type = (n.labels || []).find((l) => l && l !== 'Entity') || ''
    const key = n.uuid || n.name
    if (!arrivalOrder.has(key)) arrivalOrder.set(key, fresh++)
    return {
      uuid: key,
      name: n.name,
      kind: entityTypeName(type),
      color: roleColorVar(type),
      summary: stripIds(n.summary || ''),
      order: Math.min(arrivalOrder.get(key), 40)
    }
  })
})

// A name opened here is held in the Web beside it: its star lights, with its ties.
const openName = ref(null)
const toggleName = (n) => {
  openName.value = openName.value === n.uuid ? null : n.uuid
  emit('hold', openName.value ? n.name : '')
}
onBeforeUnmount(() => emit('hold', ''))

// ---------------------------------------------------------------------------
// The inscription

const kinds = computed(() => {
  const list = props.projectData?.ontology?.entity_types
  if (!Array.isArray(list)) return []
  return list
    .filter((e) => e && e.name && e.name !== 'Entity')
    .map((e) => ({
      id: e.name,
      word: entityTypeName(e.name),
      color: roleColorVar(e.name),
      description: e.description || '',
      examples: Array.isArray(e.examples) ? e.examples.filter(Boolean) : []
    }))
})

const ties = computed(() => {
  const list = props.projectData?.ontology?.edge_types
  if (!Array.isArray(list)) return []
  return list
    .filter((e) => e && e.name)
    .map((e) => ({
      id: e.name,
      verb: tieName(e.name),
      description: e.description || '',
      pairs: (Array.isArray(e.source_targets) ? e.source_targets : [])
        .map((p) => ({ from: entityTypeName(p.source) || 'anyone', to: entityTypeName(p.target) || 'anyone' }))
        .filter((p, idx, arr) => arr.findIndex((q) => q.from === p.from && q.to === p.to) === idx)
    }))
})

const openKind = ref(null)
const openTie = ref(null)

// ---------------------------------------------------------------------------
// The host: the philosopher who took the steps, heard once per gathering

const hostFace = ref(true)
const quoted = (line) => (locale.value === 'zh' ? `「${line}」` : `\u201c${line}\u201d`)
const HOST_HEARD = (id) => `parthenon.hearing.heard.${id}`
const hearHost = (asked = false) => {
  const h = props.host
  if (!h) return
  if (!asked) {
    const id = props.projectData?.project_id
    if (!id || !sound.enabled) return
    try {
      if (sessionStorage.getItem(HOST_HEARD(id))) return
      sessionStorage.setItem(HOST_HEARD(id), '1')
    } catch (e) { /* heard once in this visit, at least */ }
  }
  speak(voiceUrl(`speaker-${h.id}`, locale.value), asked ? { always: true } : undefined)
}
// With Listen on, the line is heard once the page may sound (after the first touch).
let hostTimer = 0
watch(
  () => [props.host?.id, props.projectData?.project_id, sound.enabled, sound.waiting],
  ([hostId, projectId, on, waiting]) => {
    clearTimeout(hostTimer)
    if (!hostId || !projectId || !on || waiting) return
    hostTimer = setTimeout(() => hearHost(false), 900)
  },
  { immediate: true }
)
onBeforeUnmount(() => clearTimeout(hostTimer))

// ---------------------------------------------------------------------------
// The door out: back to the gathering already called, or summoning the citizens

const best = computed(() => bestGathering(props.gatherings))
const returnTo = computed(() => (best.value ? standingRoute(best.value) : null))
const revisitLine = computed(() => {
  const s = gatheringStanding(best.value)
  const where = s.written ? 'written' : s.argued ? 'argued' : 'gathered'
  const line = t(`parthenon.hearing.revisit.${where}`)
  const n = props.gatherings.length
  return n > 1 ? `${line} ${t('parthenon.hearing.revisit.more', { n })}` : line
})
const crowdSize = computed(() => gatheringStanding(best.value).citizens || webCounts.value.names || 20)
const confirming = ref(false)
const confirmEl = ref(null)
watch(confirming, async (open) => {
  if (!open) return
  await nextTick()
  confirmEl.value?.focus()
})

const summoning = ref(false)
const summonError = ref('')
const canSummon = computed(
  () => props.currentPhase >= 2 && props.gatheringsRead && !!props.projectData?.project_id && !!props.projectData?.graph_id && !summoning.value
)

const summonCitizens = async () => {
  if (!canSummon.value) return
  summoning.value = true
  summonError.value = ''
  emit('log', t('parthenon.hearing.ledger.summoning'))
  try {
    const res = await createSimulation({
      project_id: props.projectData.project_id,
      graph_id: props.projectData.graph_id,
      enable_twitter: true,
      enable_reddit: true
    })
    if (res.success && res.data?.simulation_id) {
      emit('summoned', res.data.simulation_id)
      router.push({ name: 'Simulation', params: { simulationId: res.data.simulation_id } })
    } else {
      summonError.value = res.error || t('common.unknownError')
      emit('log', t('parthenon.hearing.ledger.trouble', { error: summonError.value }))
    }
  } catch (err) {
    summonError.value = err.message || t('common.unknownError')
    emit('log', t('parthenon.hearing.ledger.trouble', { error: summonError.value }))
  } finally {
    summoning.value = false
  }
}

// Begun from the steps in this tab: once the court has finished, a breath for
// the visitor to see the city knows its names, and then the citizens are
// summoned. Once only: a failure waits for the visitor to try again.
let autoTimer = 0
let autoDone = false
watch(
  () => props.autoSummon && canSummon.value && !props.gatherings.length,
  (ready) => {
    clearTimeout(autoTimer)
    if (!ready || autoDone) return
    autoTimer = setTimeout(() => {
      if (autoDone || !props.autoSummon || !canSummon.value) return
      autoDone = true
      summonCitizens()
    }, 1600)
  },
  { immediate: true }
)
onBeforeUnmount(() => clearTimeout(autoTimer))

watch(() => props.seedText, () => { unrolled.value = false })
</script>

<style scoped>
.hearing {
  width: 100%;
  max-width: 760px;
  margin: 0 auto;
  padding: 28px var(--p-gutter) 56px;
  display: flex;
  flex-direction: column;
  gap: 44px;
  min-width: 0;
}

/* Chinese is not set in capitals with inscription tracking. */
.p-eyebrow:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}

/* Status */
.status-line {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.4;
  color: var(--p-ink-2);
}

.status-ember {
  flex-shrink: 0;
  width: 10px;
  height: 10px;
  margin-top: 0.55em;
  border-radius: var(--p-radius-coin);
  background: var(--p-gold);
  box-shadow: 0 0 0 4px var(--p-terracotta-tint);
}

.status-ember.is-reading,
.status-ember.is-takingIn {
  animation: ember 1.8s ease-in-out infinite;
}

.status-ember.is-known { background: var(--p-olive); box-shadow: 0 0 0 4px var(--p-olive-tint); }
.status-ember.is-waiting,
.status-ember.is-lost { background: var(--p-ink-4); box-shadow: none; }
.status-ember.is-trouble { background: var(--p-error); box-shadow: 0 0 0 4px var(--p-error-tint); }

@keyframes ember {
  0%, 100% { box-shadow: 0 0 0 3px var(--p-terracotta-tint); }
  50% { box-shadow: 0 0 0 8px transparent; }
}

/* Section heads */
.section-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.section-note {
  font-family: var(--p-font-body);
  font-size: var(--t-xs);
  color: var(--p-ink-3);
}

/* Trouble and empty */
.trouble,
.empty {
  padding: 22px 24px;
  border: 1px solid var(--p-line-strong);
  background: var(--p-surface-2);
}

.trouble { border-color: var(--p-error); }

.trouble-title,
.empty-title {
  margin: 0 0 8px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  color: var(--p-ink);
}

.trouble-body,
.empty-body {
  margin: 0 0 16px;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  color: var(--p-ink-2);
  max-width: 40em;
}

.cause {
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.cause summary {
  cursor: pointer;
  color: var(--p-ink-2);
  font-weight: 600;
}

.cause p {
  margin: 8px 0 0;
  overflow-wrap: anywhere;
}

/* The scroll */
.parchment {
  position: relative;
  padding: clamp(28px, 5vw, 52px) clamp(20px, 5vw, 56px) clamp(28px, 5vw, 48px);
  box-shadow: var(--p-shadow-2);
  overflow: hidden;
}

.parchment::before {
  content: '';
  position: absolute;
  inset: 12px;
  border: 1px solid var(--p-line);
  pointer-events: none;
}

.parchment.folded {
  max-height: 34rem;
}

.parchment-title {
  margin: 0 0 10px;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1.05;
  color: var(--p-ink);
  text-wrap: balance;
}

.parchment-lede {
  margin: 0 0 22px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-3);
}

.parchment-body,
.parchment-prose {
  font-family: var(--p-font-serif);
  font-size: 1.0625rem;
  line-height: 1.65;
  color: var(--p-ink-2);
  max-width: 62ch;
}

.parchment-body :deep(p) { margin: 0 0 1em; }
.parchment-body :deep(p:last-child) { margin-bottom: 0; }
.parchment-body :deep(p:first-of-type)::first-letter {
  font-family: var(--p-font-display);
  font-size: 3.2em;
  line-height: 0.8;
  float: left;
  padding: 0.12em 0.12em 0 0;
  color: var(--p-terracotta);
}

.parchment-body :deep(h3),
.parchment-body :deep(h4),
.parchment-body :deep(h5) {
  font-family: var(--p-font-display);
  font-weight: 600;
  color: var(--p-ink);
  margin: 1.6em 0 0.5em;
  line-height: 1.15;
}

.parchment-body :deep(h3) { font-size: var(--t-xl); }
.parchment-body :deep(h4) { font-size: var(--t-lg); }
.parchment-body :deep(h5) { font-size: var(--t-md); font-style: italic; font-weight: 500; }
.parchment-body :deep(ul) { margin: 0 0 1em 1.2em; padding: 0; }
.parchment-body :deep(li) { margin-bottom: 0.35em; }
.parchment-body :deep(strong) { color: var(--p-ink); font-weight: 600; }

.parchment-heard .p-eyebrow { display: block; margin-bottom: 8px; }

.parchment-note {
  margin: 0 0 14px;
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.parchment-fade {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 9rem;
  background: linear-gradient(180deg, rgba(251, 248, 242, 0) 0%, var(--p-surface) 78%);
  pointer-events: none;
}

.unroll {
  align-self: flex-start;
  margin-top: 10px;
}

.bema {
  margin-top: 26px;
  padding-left: 18px;
  border-left: 2px solid var(--p-gold);
}

.bema .p-eyebrow { display: block; margin-bottom: 8px; }

.bema-question {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 500;
  line-height: 1.35;
  color: var(--p-ink);
  max-width: 42em;
}

/* The names */
.listening {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0;
  padding: 18px 20px;
  border: 1px dashed var(--p-line-strong);
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-3);
}

.listening-ember {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: var(--p-radius-coin);
  background: var(--p-ink-4);
}

.listening.live .listening-ember {
  background: var(--p-gold);
  animation: ember 1.8s ease-in-out infinite;
}

.names {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 6px 18px;
}

.name-item {
  min-width: 0;
  opacity: 0;
  animation: light-up 0.8s ease both;
  animation-delay: min(calc(var(--i, 0) * 70ms), 2800ms);
}

.name-item.open {
  grid-column: 1 / -1;
}

@keyframes light-up {
  0% { opacity: 0; transform: translateY(6px); filter: brightness(2.2); }
  55% { opacity: 1; filter: brightness(1.6); }
  100% { opacity: 1; transform: translateY(0); filter: brightness(1); }
}

.name-button {
  width: 100%;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 6px;
  background: transparent;
  border: 0;
  border-bottom: 1px solid transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  min-width: 0;
}

.name-button:hover { border-bottom-color: var(--p-line-strong); }

.name-ember {
  flex-shrink: 0;
  width: 9px;
  height: 9px;
  margin-top: 0.6em;
  border-radius: var(--p-radius-coin);
  background: var(--role, var(--p-gold));
  box-shadow: 0 0 10px 1px var(--role, var(--p-gold));
}

.name-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 500;
  line-height: 1.15;
  color: var(--p-ink);
  overflow-wrap: anywhere;
}

.kind {
  font-family: var(--p-font-body);
  font-size: var(--t-xs);
  color: var(--p-ink-3);
}

.name-about {
  margin: 4px 0 14px 27px;
  padding-left: 14px;
  border-left: 1px solid var(--role, var(--p-gold));
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.55;
  color: var(--p-ink-2);
  max-width: 60ch;
}

/* The inscription */
.tablet {
  padding: 26px 28px 30px;
  border: 1px solid var(--p-line-strong);
  border-top: 2px solid var(--p-gold);
  background: var(--p-surface-2);
}

.tablet-waiting {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-3);
}

.tablet-part + .tablet-part {
  margin-top: 28px;
  padding-top: 24px;
  border-top: 1px solid var(--p-line);
}

.tablet-heading {
  margin: 0 0 12px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

/* Chinese is not set in capitals with inscription tracking. */
.tablet-heading:lang(zh),
.host-floor:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.04em;
  text-transform: none;
}

.carved {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 6px;
}

.carved-item { min-width: 0; }
.carved-item.open { flex-basis: 100%; }

.carved-button {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  /* A thumb needs 44px; the row gap below keeps rows apart. */
  min-height: 44px;
  padding: 10px 12px;
  background: transparent;
  border: 1px solid transparent;
  color: var(--p-ink);
  cursor: pointer;
  text-align: left;
}

.carved-button:hover,
.carved-item.open .carved-button {
  border-color: var(--p-line-strong);
}

.carved-mark {
  width: 8px;
  height: 8px;
  border-radius: var(--p-radius-coin);
  background: var(--role, var(--p-gold));
  flex-shrink: 0;
}

.carved-word {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 500;
  line-height: 1.1;
}

.carved-verb {
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  font-weight: 500;
  line-height: 1.1;
}

.carved-detail {
  margin: 6px 0 12px 10px;
  padding-left: 14px;
  border-left: 1px solid var(--p-line-strong);
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.55;
  color: var(--p-ink-2);
  max-width: 60ch;
}

.carved-detail p { margin: 0 0 8px; }

.carved-examples {
  display: flex;
  gap: 10px;
  align-items: baseline;
  flex-wrap: wrap;
  font-size: var(--t-sm);
}

.pairs {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--t-sm);
}

.pairs li {
  display: flex;
  flex-wrap: wrap;
  gap: 0 8px;
  align-items: baseline;
}

.pair-word { color: var(--p-ink); }
.pair-verb { font-style: italic; color: var(--p-ink-3); }

/* The host: who took the steps keeps the floor */
.host {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 18px 22px;
  align-items: center;
  padding: 18px 22px 18px 18px;
  border: 1px solid var(--p-line);
  border-left: 2px solid var(--p-gold);
  background:
    radial-gradient(ellipse 60% 120% at 0% 50%, rgba(240, 182, 96, 0.1), transparent 70%),
    var(--p-surface-2);
  min-width: 0;
}

.host-coin {
  position: relative;
  display: grid;
  place-items: center;
  width: 92px;
  height: 92px;
  border-radius: var(--p-radius-coin);
  overflow: hidden;
  background: var(--p-surface);
  box-shadow: 0 0 0 1px var(--p-gold), 0 0 0 5px rgba(240, 182, 96, 0.12), 0 10px 30px rgba(0, 0, 0, 0.45);
}

.host-coin img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: 50% 22%;
}

.host-letter {
  font-family: var(--p-font-display);
  font-size: 2.2rem;
  color: var(--p-gold);
}

.host-copy {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  min-width: 0;
}

.host-floor {
  color: var(--p-gold);
}

.host-line {
  margin: 0;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-xl);
  font-weight: 500;
  line-height: 1.25;
  color: var(--p-ink);
  text-wrap: balance;
}

.host-line:lang(zh) {
  font-style: normal;
  font-family: var(--p-font-serif);
}

.host-hear {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  margin-left: -8px;
  padding: 0 8px;
  background: transparent;
  border: 0;
  color: var(--p-ink-3);
  font-family: var(--p-font-body);
  font-size: var(--t-sm);
  cursor: pointer;
}

.host-hear:hover,
.host-hear:focus-visible {
  color: var(--p-ink);
}

/* Doors */
.door-row {
  align-self: stretch;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
}

.empty .door-row { margin-top: 4px; }
.empty .bema { margin: 0 0 18px; }

.revisit-line {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  line-height: 1.5;
  color: var(--p-ink-2);
  max-width: 44em;
}

.new-crowd { min-height: 44px; }

.confirm {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 44em;
  padding: 16px 18px;
  border: 1px solid var(--p-line-strong);
  border-left: 2px solid var(--p-terracotta);
  background: var(--p-surface-2);
}

.confirm-title {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 500;
  color: var(--p-ink);
}

.confirm-body {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.55;
  color: var(--p-ink-2);
}

.confirm .p-button { min-height: 44px; }

/* Summon */
.summon-section {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
  padding-top: 8px;
}

.summon {
  min-width: min(100%, 280px);
  font-size: var(--t-md);
  min-height: 54px;
}

.summon-ember {
  width: 10px;
  height: 10px;
  border-radius: var(--p-radius-coin);
  background: currentColor;
  animation: ember 1.2s ease-in-out infinite;
}

.summon-when {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.summon-trouble {
  padding: 14px 16px;
  border: 1px solid var(--p-error);
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  color: var(--p-ink-2);
}

.summon-trouble p { margin: 0 0 6px; }

@media (max-width: 899px) {
  .hearing {
    padding: 20px 16px 48px;
    gap: 36px;
  }

  .parchment.folded { max-height: 28rem; }
  .parchment-title { font-size: var(--t-xl); }
  .host { grid-template-columns: auto minmax(0, 1fr); padding: 14px; gap: 14px; }
  .host-coin { width: 68px; height: 68px; }
  .host-line { font-size: var(--t-lg); }
  .door-row > .p-button { flex: 1 1 auto; justify-content: center; }
  .tablet { padding: 20px 16px 22px; }
  .names { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); }
}

@media (prefers-reduced-motion: reduce) {
  .name-item {
    animation: none;
    opacity: 1;
  }

  .status-ember,
  .listening-ember,
  .summon-ember {
    animation: none;
  }
}
</style>
