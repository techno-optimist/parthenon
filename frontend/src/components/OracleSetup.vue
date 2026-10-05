<template>
  <section class="oracle-setup" :aria-labelledby="`${uid}-heading`">
    <header class="oracle-heading">
      <svg class="oracle-mark" :viewBox="TRIPOD.viewBox" aria-hidden="true"><path v-for="part in tripodMark('still')" :key="part.id" :d="part.d" /></svg>
      <div><p class="p-eyebrow">{{ copy.oracle }}</p><h3 :id="`${uid}-heading`">{{ copy.heading }}</h3><p>{{ copy.intro }}</p></div>
    </header>

    <div v-show="!advancedOpen" class="oracle-composer">
      <form class="brief-form" @submit.prevent="askOracle">
        <label :for="`${uid}-brief`">{{ state.proposal ? copy.refineLabel : copy.briefLabel }}</label>
        <p :id="`${uid}-brief-help`" class="field-help">{{ copy.briefHelp }}</p>
        <textarea :id="`${uid}-brief`" v-model="brief" rows="4" maxlength="6000" :disabled="disabled" :placeholder="copy.placeholder" :aria-describedby="`${uid}-brief-help`" @input="edited" />
        <div class="dictation-line">
          <template v-if="dictationSupported">
            <button type="button" class="p-button ghost text-button" :disabled="disabled || state.pending || micStatus === 'stopping'" :aria-pressed="micStatus !== 'idle'" @click="toggleDictation">{{ micStatus === 'idle' ? copy.dictate : copy.stopDictation }}</button>
            <span>{{ copy.micDisclosure }}</span>
          </template>
          <span v-else>{{ copy.dictationFallback }}</span>
        </div>
        <p v-if="micStatus !== 'idle'" role="status" class="mic-status">{{ micStatus === 'listening' ? copy.listening : micStatus === 'starting' ? copy.micStarting : copy.micStopping }}</p>
        <p v-if="micError" role="alert" class="inline-error">{{ copyLine(micError) }}</p>

        <details class="sources-details">
          <summary>{{ copy.sources }}</summary>
          <label :for="`${uid}-sources`">{{ copy.sourcesLabel }}</label>
          <textarea :id="`${uid}-sources`" v-model="sources" rows="4" maxlength="8000" :disabled="disabled" @input="edited" />
          <p class="field-help">{{ copy.sourcesHelp }} <span class="count">{{ sources.length }}/8000</span></p>
        </details>

        <div class="ask-actions">
          <button type="submit" class="p-button gold-button" :disabled="disabled || state.pending || !brief.trim()">{{ state.pending ? copy.thinking : state.proposal ? copy.refine : copy.propose }}</button>
          <button v-if="state.pending" type="button" class="p-button ghost text-button" @click="cancelRequest">{{ copy.cancel }}</button>
          <p>{{ copy.callBound }}</p>
        </div>
        <p v-if="state.pending" role="status" class="request-status">{{ copy.waiting }}</p>
        <p v-if="state.notice" role="status" class="request-status">{{ noticeText }}</p>
        <p v-if="state.error" role="alert" class="inline-error">{{ copyLine(state.error) }}</p>
        <InviteLine v-if="showInvite" @given="inviteGiven" />
        <div v-if="state.clarification" class="clarification" role="status"><strong>{{ copy.clarification }}</strong><p>{{ state.clarification }}</p><p class="field-help">{{ copy.clarificationHelp }}</p></div>
      </form>

      <section v-if="state.proposal" class="proposal-review" :aria-labelledby="`${uid}-review`">
        <header class="review-heading"><div><p class="p-eyebrow">{{ copy.reviewEyebrow }}</p><h4 :id="`${uid}-review`">{{ copy.reviewHeading }}</h4></div><span class="simulation-label p-eyebrow">{{ copy.simulation }}</span></header>
        <p class="field-help">{{ copy.reviewHelp }}</p>
        <div class="proposal-overview">
          <h5 class="proposal-title">{{ state.proposal.stage.title }}</h5>
          <p class="overview-setting">{{ state.proposal.stage.setting }}</p>
          <p class="overview-question">{{ state.proposal.stage.question }}</p>
          <dl class="overview-facts">
            <div><dt>{{ copy.format }}</dt><dd>{{ labelOf(FORMATS.find(f => f.id === state.proposal.stage.format)) }}</dd></div>
            <div><dt>{{ copy.duration }}</dt><dd>{{ durationLabel(RUN_LENGTHS.find(l => l.id === state.proposal.runLength)) }}</dd></div>
            <div class="wide"><dt>{{ copy.trigger }}</dt><dd>{{ state.proposal.stage.happensNext }}</dd></div>
          </dl>
          <p class="overview-people"><strong>{{ state.proposal.origin === 'advanced' ? copy.speakerSimulations : copy.speakers }}</strong><span>{{ state.proposal.stage.speakers.map(s => s.name).join(' · ') }}</span></p>
          <p class="overview-people"><strong>{{ copy.civilians }}</strong><span>{{ state.proposal.stage.audience.map(a => a.name).join(' · ') }}</span></p>
        </div>
        <details class="stage-details">
          <summary>{{ copy.editDetails }}</summary>
        <div class="review-grid">
          <label class="wide">{{ copy.title }}<input v-model="state.proposal.stage.title" maxlength="120" :disabled="disabled" @input="edited" /></label>
          <label>{{ copy.format }}<select v-model="state.proposal.stage.format" :disabled="disabled" @change="edited"><option v-for="f in FORMATS" :key="f.id" :value="f.id">{{ labelOf(f) }}</option></select></label>
          <label>{{ copy.era }}<select v-model="state.proposal.stage.era" :disabled="disabled" @change="edited"><option v-for="era in ERAS" :key="era.id" :value="era.id">{{ labelOf(era) }}</option></select></label>
          <label class="wide">{{ copy.setting }}<input v-model="state.proposal.stage.setting" maxlength="300" :disabled="disabled" @input="edited" /></label>
          <label class="wide">{{ copy.topic }}<textarea v-model="state.proposal.stage.topic" rows="2" maxlength="3000" :disabled="disabled" @input="edited" /></label>
          <label class="wide">{{ copy.question }}<textarea v-model="state.proposal.stage.question" rows="2" maxlength="1500" :disabled="disabled" @input="edited" /></label>
          <label class="wide">{{ copy.trigger }}<textarea v-model="state.proposal.stage.happensNext" rows="2" maxlength="1000" :disabled="disabled" @input="edited" /></label>
          <label class="wide">{{ copy.duration }}<select v-model="state.proposal.runLength" :disabled="disabled" @change="edited"><option v-for="length in availableLengths" :key="length.id" :value="length.id">{{ durationLabel(length) }}</option></select><span class="field-help">{{ copy.durationHelp }}</span></label>
        </div>

        <div class="review-people">
          <section><h5>{{ state.proposal.origin === 'advanced' ? copy.speakerSimulations : copy.speakers }}</h5><p class="field-help">{{ state.proposal.origin === 'advanced' ? copy.advancedSpeakersHelp : copy.speakersHelp }}</p><details v-for="(speaker, index) in state.proposal.stage.speakers" :key="speaker.key || speaker.figureId || index" class="person-detail"><summary>{{ speaker.name }}<span>{{ speaker.role }}</span></summary><p class="documented-ideas">{{ speaker.ideas }}</p><label>{{ state.proposal.origin === 'advanced' ? copy.editedOpening : copy.opening }}<textarea v-model="speaker.words" rows="5" maxlength="4000" :disabled="disabled" @input="edited" /></label></details></section>
          <section><h5>{{ copy.civilians }} <span class="count">{{ state.proposal.stage.audience.length }}</span></h5><p class="field-help">{{ copy.civiliansHelp }}</p><details v-for="(member, index) in state.proposal.stage.audience" :key="member.key || member.name || index" class="person-detail"><summary>{{ member.name }}</summary><label>{{ copy.stake }}<textarea v-model="member.description" rows="2" maxlength="400" :disabled="disabled" @input="edited" /></label></details></section>
        </div>
        </details>

        <aside class="scenario-basis"><h5>{{ copy.basis }}</h5><p>{{ sources.trim() ? copy.userSources : copy.hypothetical }}</p><ul><li v-for="(assumption, index) in state.proposal.assumptions" :key="index">{{ assumption }}</li></ul></aside>
        <ul v-if="problems.length" class="review-problems" role="status"><li v-for="problem in problems" :key="problem">{{ problem }}</li></ul>
        <div class="handoff"><button type="button" class="p-button gold-button" :disabled="disabled || state.pending || problems.length > 0" @click="continueStage">{{ copy.continue }}</button><p>{{ copy.handoffHelp }}</p></div>
      </section>
    </div>

    <div class="advanced-control"><button type="button" class="p-button ghost text-button" :aria-expanded="advancedOpen" :aria-controls="`${uid}-advanced`" :disabled="disabled" @click="toggleAdvanced">{{ advancedOpen ? copy.back : copy.advanced }}</button><p>{{ copy.advancedHelp }}</p></div>
    <section v-if="advancedOpen" :id="`${uid}-advanced`" class="advanced-builder" :aria-label="copy.advanced"><StageBuilder :disabled="disabled" :initial-stage="advancedDraft || state.proposal?.stage" @stage-change="advancedChanged" @use-stage="advancedUseStage" /></section>
    <p v-if="storageNote" class="draft-note" role="status">{{ copyLine(storageNote) }}</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import StageBuilder from './StageBuilder.vue'
import InviteLine from './InviteLine.vue'
import { proposeStage } from '../api/parthenon.js'
import { access, inviteNeeded } from '../parthenon/access.js'
import { ERAS, FORMATS } from '../parthenon/composeStage.js'
import { RUN_LENGTHS } from '../parthenon/vocabulary.js'
import { allowedRunLengths, clampRunLength } from '../parthenon/limits.js'
import { TRIPOD, tripodMark } from '../parthenon/oracle.js'
import { createProposalSession, proposalSeed, reviewProblems, validateProposal } from '../parthenon/oracleSetup.js'
import { createDictation } from '../parthenon/dictation.js'

const props = defineProps({ disabled: { type: Boolean, default: false } })
const emit = defineEmits(['use-stage'])
const { locale, t } = useI18n()
const uid = `oracle-${String(useId()).replace(/[^A-Za-z0-9_-]/g, '')}`
const en = {
  oracle: 'The Oracle of Parthenon', heading: 'What should this civilization face?', intro: 'Describe a world and a decision. The Oracle will propose a gathering for you to review.',
  briefLabel: 'Your brief', refineLabel: 'Tell the Oracle what to change', briefHelp: 'A few sentences are enough. You can name a place, an idea, or a tension to explore.', placeholder: 'A city weighs AI tutors in its schools. Let Socrates and Aristotle debate with teachers, parents, and students.',
  dictate: 'Start dictation', stopDictation: 'Stop dictation', micDisclosure: 'Browser dictation may send audio to its speech service. Start only if you agree.', dictationFallback: 'Type your brief, or use your device’s keyboard dictation. Browser dictation is unavailable here.', listening: 'Listening. Your final words will appear in the brief.', micStarting: 'Waiting for microphone permission…', micStopping: 'Stopping dictation…',
  sources: 'Add source context (optional)', sourcesLabel: 'Paste excerpts and their source URLs', sourcesHelp: 'For contemporary events, supply the relevant text. Links alone are not verified evidence. The Oracle does not browse.',
  propose: 'Ask the Oracle', refine: 'Refine this proposal', thinking: 'The Oracle is drafting…', cancel: 'Stop waiting', callBound: 'One request per ask. Drafting prepares a proposal.', waiting: 'You can keep editing. Changes will stop this request from replacing your work.',
  clarification: 'One detail would help', clarificationHelp: 'Answer in the brief above, then ask again. Your original brief is kept as context.', reviewEyebrow: 'Your proposed civilization', reviewHeading: 'Review the gathering', simulation: 'Simulation', reviewHelp: 'Refine the proposal in your own words, or open the details to edit.',
  title: 'Title', format: 'Gathering format', era: 'Era', setting: 'Setting', topic: 'The matter', question: 'Question to explore', trigger: 'What happens next', duration: 'Simulated duration', durationHelp: 'Choose a supported story length. You will confirm it again before beginning.', editDetails: 'Edit stage details',
  speakers: 'Historical voices, simulated', speakersHelp: 'Documented ideas guide these figures; their opening words are imagined.', opening: 'Generated opening words — editable', civilians: 'Fictional civilian roles', civiliansHelp: 'These are imagined roles and positions, not claims about real people or groups.', stake: 'Stake and initial position', basis: 'Scenario basis and assumptions', userSources: 'User-supplied context, unverified. No web lookup was performed.', hypothetical: 'A hypothetical scenario. Contemporary details are assumptions.',
  speakerSimulations: 'Speaker simulations', advancedSpeakersHelp: 'Speaker descriptions and supplied speech form a simulation, not actual testimony.', editedOpening: 'Opening words — editable',
  continue: 'Review and continue', handoffHelp: 'This prepares your scroll below. Begin the gathering there when you are ready.', advanced: 'Open advanced controls', back: 'Return to Oracle review', advancedHelp: 'Choose from the full roster, crowd presets, and the existing stage builder.', saved: 'Draft saved in this browser.', restored: 'Your last Oracle draft was restored.', storageUnavailable: 'Browser storage is unavailable. Keep this page open to retain your draft.', cancelled: 'Stopped waiting. Your draft is kept.',
  micDenied: 'Microphone permission was denied. You can type or use device dictation.', micNoSpeech: 'No speech was detected. Try dictation again or type your brief.', micNetwork: 'The browser speech service could not connect. Your typed brief is kept.', micFailed: 'Browser dictation could not start. You can type or use device dictation.', advancedRefine: 'This draft uses advanced options. Continue editing it in advanced controls; natural-language refinements use the bounded historical roster.',
  editsKept: 'Your edits are kept. Ask the Oracle again to use them.', briefTooLong: 'Shorten the brief and clarification answer to 6000 characters in total.', advancedAssumption: 'Stage edited in advanced controls.',
  proposalNeeded: 'Ask the Oracle to propose a stage first.', titleNeeded: 'Add the title.', settingNeeded: 'Add the setting.', topicNeeded: 'Add the topic.', questionNeeded: 'Add the question.', triggerNeeded: 'Add the upcoming trigger.', civiliansNeeded: 'Add fictional civilians to the gathering.', openingNeeded: 'Give each speaker opening words.', civilianDetailsNeeded: 'Give each civilian a name and description.', durationNeeded: 'Choose an available run duration.',
}
const zh = {
  oracle: '帕特农神谕', heading: '这个文明将面对什么？', intro: '描述一个世界与待决问题。神谕将提出一场集会，供你审阅。', briefLabel: '你的构想', refineLabel: '告诉神谕要改变什么', briefHelp: '几句话就够了。可以描述地点、想法或想探索的矛盾。', placeholder: '一座城邦考虑在学校采用 AI 导师。让苏格拉底与亚里士多德和教师、家长、学生共同辩论。',
  propose: '求问神谕', refine: '修改这份提案', thinking: '神谕正在起草…', cancel: '停止等待', sources: '添加来源背景（可选）', sourcesLabel: '粘贴摘录及其来源链接', sourcesHelp: '涉及当代事件时，请提供相关原文。链接本身不是已核实的证据。神谕不会浏览网页。',
  reviewEyebrow: '你的文明提案', reviewHeading: '审阅集会', simulation: '模拟', title: '标题', format: '集会形式', era: '时代', setting: '地点与背景', topic: '议题', question: '要探索的问题', trigger: '接下来发生什么', duration: '模拟时长', editDetails: '编辑集会细节', speakers: '历史人物的模拟声音', civilians: '虚构的民众角色', opening: '生成的开场白，可编辑', stake: '利益与初始立场', basis: '情景依据与假设', continue: '审阅并继续', handoffHelp: '这会在下方准备卷轴。准备好后，请在那里开始集会。', advanced: '打开高级选项', back: '返回神谕审阅', saved: '草稿已保存在此浏览器中。', restored: '已恢复你上次的神谕草稿。',
  dictate: '开始听写', stopDictation: '停止听写', micDisclosure: '浏览器听写可能把音频发送到其语音服务。仅在同意时开始。', dictationFallback: '输入构想，或使用设备键盘的听写功能。这里不支持浏览器听写。', listening: '正在聆听。识别完成的文字将出现在构想中。', micStarting: '正在等待麦克风许可…', micStopping: '正在停止听写…',
  callBound: '每次求问只发送一次请求，起草仅用于准备提案。', waiting: '你可以继续编辑；修改后，这次请求的回答不会覆盖你的草稿。',
  clarification: '还需要一个细节', clarificationHelp: '在上方的构想中回答，然后再次求问。你的原始构想会保留为背景。', reviewHelp: '用自己的话修改提案，或打开细节逐项编辑。',
  durationHelp: '选择支持的故事时长。开始前，你还会再次确认。', speakersHelp: '这些人物以文献记载的思想为基础；开场白是模拟创作。', civiliansHelp: '这些角色与立场均为虚构，不代表真实个人或群体的观点。',
  userSources: '由你提供的背景，尚未核实。未进行网页检索。', hypothetical: '这是一个假设情境；当代细节均为假设。',
  speakerSimulations: '发言者模拟角色', advancedSpeakersHelp: '人物描述与提供的发言用于构建模拟，并非真实证词。', editedOpening: '开场白，可编辑',
  advancedHelp: '使用完整人物名册、人群预设和现有舞台编辑器。', storageUnavailable: '浏览器存储不可用。请保持此页面打开，以保留草稿。', cancelled: '已停止等待。你的草稿仍然保留。',
  micDenied: '麦克风许可被拒绝。你可以输入文字，或使用设备听写。', micNoSpeech: '未检测到语音。请重试听写，或输入构想。', micNetwork: '浏览器语音服务无法连接。你已输入的构想仍然保留。', micFailed: '浏览器听写无法启动。你可以输入文字，或使用设备听写。', advancedRefine: '此草稿使用了高级选项。请继续在高级选项中编辑；自然语言修改仅支持神谕的历史人物名册。',
  editsKept: '你的修改仍然保留。请再次求问神谕，让它使用这些修改。', briefTooLong: '请将构想与补充回答缩短至总计 6000 个字符以内。', advancedAssumption: '舞台已在高级选项中编辑。',
  proposalNeeded: '请先求问神谕，生成舞台提案。', titleNeeded: '请添加标题。', settingNeeded: '请添加地点与背景。', topicNeeded: '请添加议题。', questionNeeded: '请添加问题。', triggerNeeded: '请添加即将发生的事件。', civiliansNeeded: '请为集会添加虚构的民众角色。', openingNeeded: '请为每位发言者添加开场白。', civilianDetailsNeeded: '请为每个民众角色添加名称与描述。', durationNeeded: '请选择可用的模拟时长。',
}
// Every supported locale gets readable English for newer strings, never keys.
const copy = computed(() => locale.value.startsWith('zh') ? { ...en, ...zh } : en)
// Local status lines follow a language switch; model/user prose stays intact.
const copyLine = value => {
  const key = Object.keys(en).find(key => en[key] === value || zh[key] === value)
  return key ? copy.value[key] : value
}
const labelOf = item => locale.value.startsWith('zh') ? item.zh?.label || item.label : item.label
const durationLabel = length => `${t(`parthenon.length.${length.id}`)} · ${length.rounds} ${locale.value.startsWith('zh') ? '模拟小时' : 'simulated hours'}`
const brief = ref(''), sources = ref(''), clarificationContext = ref('')
const advancedOpen = ref(false), advancedDraft = ref(null), showInvite = ref(false), storageNote = ref('')
const session = createProposalSession({ ask: proposeStage, wrapState: reactive })
const state = session.state
watch(() => state.cityCode, code => { if (code === 'invite_needed') showInvite.value = true })
const availableLengths = computed(() => access.public && access.limits ? allowedRunLengths(RUN_LENGTHS, access.limits.max_run) : RUN_LENGTHS)
const problems = computed(() => {
  const words = copy.value
  const translated = { 'Ask the Oracle to propose a stage first.': words.proposalNeeded, 'Add the title.': words.titleNeeded, 'Add the setting.': words.settingNeeded, 'Add the topic.': words.topicNeeded, 'Add the question.': words.questionNeeded, 'Add the upcoming trigger.': words.triggerNeeded, 'Add fictional civilians to the gathering.': words.civiliansNeeded, 'Give each speaker opening words.': words.openingNeeded, 'Give each civilian a name and description.': words.civilianDetailsNeeded, 'Choose an available run duration.': words.durationNeeded }
  return reviewProblems(state.proposal, availableLengths.value.map(l => l.id), locale.value).map(problem => translated[problem] || problem)
})
const noticeText = computed(() => copyLine(state.notice))
const edited = () => session.edited()
watch(availableLengths, () => {
  if (state.proposal && access.public && access.limits) state.proposal.runLength = clampRunLength(state.proposal.runLength, RUN_LENGTHS, access.limits.max_run)
})

const micStatus = ref('idle'), micError = ref(''), dictationSupported = ref(false)
let dictation = null
function toggleDictation() {
  if (micStatus.value !== 'idle') { dictation?.stop(); return }
  micError.value = ''
  dictation?.start(locale.value.startsWith('zh') ? 'zh-CN' : locale.value === 'en' ? 'en-US' : locale.value)
}

async function askOracle() {
  if (props.disabled || state.pending || !brief.value.trim()) return
  if (inviteNeeded()) { showInvite.value = true; return }
  if (state.proposal) {
    try { validateProposal(state.proposal) } catch { state.error = copy.value.advancedRefine; return }
  }
  dictation?.dispose()
  const requestBrief = clarificationContext.value
    ? `${clarificationContext.value}\n\nUser answer: ${brief.value}` : brief.value
  if (requestBrief.length > 6000) { state.error = copy.value.briefTooLong; return }
  const accepted = await session.request({ brief: requestBrief, sources: sources.value, current: state.proposal || undefined })
  if (!accepted) return
  if (state.clarification) {
    clarificationContext.value = `Original brief: ${requestBrief}\n\nOracle question: ${state.clarification}`
    brief.value = ''
  } else {
    clarificationContext.value = ''; brief.value = ''; advancedDraft.value = null
    if (access.public && access.limits) state.proposal.runLength = clampRunLength(state.proposal.runLength, RUN_LENGTHS, access.limits.max_run)
  }
}
const inviteGiven = () => { showInvite.value = false; state.error = ''; /* A new ask stays explicit. */ }
function cancelRequest() { session.cancel(); state.notice = copy.value.cancelled }
function toggleAdvanced() {
  dictation?.dispose(); session.cancel()
  if (!advancedOpen.value && state.proposal) advancedDraft.value = JSON.parse(JSON.stringify(state.proposal.stage))
  if (advancedOpen.value && advancedDraft.value) {
    if (state.proposal) { state.proposal.stage = JSON.parse(JSON.stringify(advancedDraft.value)); state.proposal.origin = 'advanced' }
    else if (advancedDraft.value.speakers?.some(s => s.name.trim())) state.proposal = { stage: JSON.parse(JSON.stringify(advancedDraft.value)), origin: 'advanced', runLength: availableLengths.value.find(l => l.id === 'day')?.id || availableLengths.value[0].id, assumptions: [copy.value.advancedAssumption], sourceBasis: sources.value.trim() ? 'user-supplied' : 'hypothetical' }
  }
  advancedOpen.value = !advancedOpen.value
}
function advancedChanged(stage) {
  advancedDraft.value = stage
  // The saved proposal must track the open builder's latest edits too:
  // opening advanced after a reload starts from this same accepted stage.
  if (state.proposal) {
    state.proposal.stage = JSON.parse(JSON.stringify(stage))
    state.proposal.origin = 'advanced'
  }
}
function continueStage() {
  if (props.disabled || state.pending || problems.value.length) return
  const seed = proposalSeed(state.proposal, sources.value)
  emit('use-stage', { ...seed, file: new File([seed.markdown], seed.fileName, { type: 'text/markdown' }), recordQuestion: seed.question, era: state.proposal.stage.era, stage: JSON.parse(JSON.stringify(state.proposal.stage)), runLength: state.proposal.runLength })
}
function advancedUseStage(payload) {
  advancedDraft.value = payload.stage
  state.proposal = { ...(state.proposal || { assumptions: [copy.value.advancedAssumption], sourceBasis: sources.value.trim() ? 'user-supplied' : 'hypothetical', runLength: availableLengths.value.find(l => l.id === 'day')?.id || availableLengths.value[0].id }), stage: payload.stage, origin: 'advanced' }
  // Preserve the advanced builder's established, more permissive handoff,
  // including its record-language question and seed. Provenance is additive.
  const seed = proposalSeed(state.proposal, sources.value, payload)
  emit('use-stage', { ...payload, markdown: seed.markdown, file: new File([seed.markdown], payload.fileName, { type: 'text/markdown' }), runLength: state.proposal.runLength })
}

const STORAGE = 'parthenon.oracleSetup.v1'
let saveTimer = null
function saveDraft() {
  try {
    window.localStorage.setItem(STORAGE, JSON.stringify({ brief: brief.value, sources: sources.value, proposal: state.proposal, advancedDraft: advancedDraft.value, clarificationContext: clarificationContext.value, clarification: state.clarification }))
    storageNote.value = copy.value.saved
  } catch { storageNote.value = copy.value.storageUnavailable }
}
onMounted(() => {
  try {
    const raw = window.localStorage.getItem(STORAGE)
    if (raw && raw.length < 80000) {
      const saved = JSON.parse(raw)
      brief.value = typeof saved.brief === 'string' ? saved.brief.slice(0, 6000) : ''
      sources.value = typeof saved.sources === 'string' ? saved.sources.slice(0, 8000) : ''
      clarificationContext.value = typeof saved.clarificationContext === 'string' ? saved.clarificationContext.slice(0, 6000) : ''
      state.clarification = typeof saved.clarification === 'string' ? saved.clarification.slice(0, 300).trim() : ''
      if (saved.proposal) state.proposal = validateProposal(saved.proposal, { incomplete: true, advanced: true })
      if (saved.advancedDraft && typeof saved.advancedDraft === 'object' && Array.isArray(saved.advancedDraft.speakers) && Array.isArray(saved.advancedDraft.audience)) advancedDraft.value = saved.advancedDraft
      storageNote.value = copy.value.restored
    }
  } catch { /* Corrupt or blocked storage must not prevent typed setup. */ }
  dictation = createDictation({
    Recognition: window.SpeechRecognition || window.webkitSpeechRecognition, secure: window.isSecureContext,
    onText: text => { edited(); brief.value = `${brief.value}${brief.value ? ' ' : ''}${text}`.slice(0, 6000) },
    onStatus: status => { micStatus.value = status },
    onError: error => { micError.value = ['not-allowed', 'service-not-allowed'].includes(error) ? copy.value.micDenied : error === 'no-speech' ? copy.value.micNoSpeech : error === 'network' ? copy.value.micNetwork : copy.value.micFailed },
  })
  dictationSupported.value = dictation.supported
  window.addEventListener('pagehide', saveDraft)
})
watch([brief, sources, () => state.proposal, advancedDraft, clarificationContext, () => state.clarification], () => { clearTimeout(saveTimer); saveTimer = setTimeout(saveDraft, 350) }, { deep: true })
watch(() => props.disabled, disabled => { if (disabled) { session.cancel(); dictation?.dispose() } })
onBeforeUnmount(() => { window.removeEventListener('pagehide', saveDraft); clearTimeout(saveTimer); saveDraft(); session.cancel(); dictation?.dispose() })
</script>

<style scoped>
.oracle-setup { width: 100%; max-width: 900px; color: var(--p-ink-2); font-family: var(--p-font-body); padding-block: 2rem 1.5rem; }
.oracle-heading { display: flex; align-items: flex-start; gap: 1.5rem; margin-bottom: 1.5rem; }
.oracle-heading > div { min-width: 0; }
.oracle-mark { width: 3rem; flex: 0 0 3rem; fill: none; stroke: var(--p-gold); stroke-width: 1.25; margin-top: .5rem; }
.p-eyebrow { margin: 0 0 .75rem; }
h3, h4, h5 { color: var(--p-ink); font-family: var(--p-font-display); font-weight: 500; text-wrap: balance; }
h3 { font-size: var(--t-3xl); line-height: 1.1; letter-spacing: -.02em; margin: 0 0 .75rem; }
h4 { font-size: var(--t-2xl); line-height: 1.15; margin: 0; }
h5 { font-size: var(--t-lg); line-height: 1.3; margin: 0 0 .5rem; }
p { line-height: 1.6; max-width: 65ch; margin: .5rem 0; text-wrap: pretty; }
.oracle-heading p:last-child { color: var(--p-ink-3); }
.brief-form { padding: 1.5rem; background: var(--p-surface-2); background-image: var(--p-marble-texture); border-left: 2px solid var(--p-gold); }
label { display: grid; gap: .5rem; color: var(--p-ink-3); font-family: var(--p-font-inscription); font-size: var(--t-xs); font-weight: 600; letter-spacing: var(--track-inscription); line-height: 1.5; }
.brief-form > label { color: var(--p-ink); font-size: var(--t-sm); }
.field-help { color: var(--p-ink-3); font-family: var(--p-font-body); font-size: var(--t-sm); font-weight: 400; letter-spacing: 0; line-height: 1.6; }
input, select, textarea { box-sizing: border-box; width: 100%; min-width: 0; border: 1px solid var(--p-control-border); border-radius: var(--p-radius); background: var(--p-surface); color: var(--p-ink); padding: .75rem; font-family: var(--p-font-body); font-size: var(--t-md); font-weight: 400; letter-spacing: 0; line-height: 1.55; }
input, select { min-height: 48px; }
textarea { resize: vertical; min-height: 4rem; }
.brief-form > textarea { min-height: 10rem; margin-top: .5rem; }
input::placeholder, textarea::placeholder { color: var(--p-ink-4); opacity: 1; }
input:disabled, select:disabled, textarea:disabled { background: var(--p-surface-2); color: var(--p-ink-3); }
summary:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible { outline: 2px solid var(--p-gold); outline-offset: 3px; }
.text-button { min-height: 48px; }
.dictation-line { display: flex; align-items: center; gap: .75rem; margin-block: .75rem 1.5rem; font-size: var(--t-xs); line-height: 1.6; color: var(--p-ink-3); }
.dictation-line button { flex: 0 0 auto; }
.sources-details { margin-block: 1.5rem; }
summary { box-sizing: border-box; min-height: 48px; cursor: pointer; padding-block: .75rem; color: var(--p-gold); font-family: var(--p-font-inscription); font-size: var(--t-xs); font-weight: 600; letter-spacing: var(--track-inscription); line-height: 1.5; }
.sources-details label { margin-block: .75rem; }
.ask-actions { display: flex; align-items: center; flex-wrap: wrap; gap: .75rem 1.5rem; margin-top: 1.5rem; }
.ask-actions p { font-size: var(--t-xs); color: var(--p-ink-3); }
.request-status, .mic-status { font-size: var(--t-sm); color: var(--p-gold); }
.inline-error { padding: .75rem 1rem; border-left: 2px solid var(--p-error); background: var(--p-error-tint); color: var(--p-error); font-size: var(--t-sm); }
.clarification { margin-top: 1.5rem; }
.proposal-review { margin-top: 3rem; }
.proposal-overview { margin-block: 1.5rem; }
.proposal-title { font-size: var(--t-xl); margin: 0; }
.overview-setting { margin-top: .5rem; font-size: var(--t-sm); color: var(--p-ink-3); }
.overview-question { font-family: var(--p-font-serif); font-size: var(--t-lg); line-height: 1.55; margin-block: 1.5rem; }
.overview-facts { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1.5rem; margin-block: 1.5rem; }
.overview-facts dt, .overview-people strong { font-family: var(--p-font-inscription); font-size: var(--t-xs); color: var(--p-ink-3); font-weight: 600; letter-spacing: var(--track-inscription); }
.overview-facts dd { font-size: var(--t-md); line-height: 1.6; margin: .5rem 0 0; }
.overview-people { display: grid; gap: .5rem; font-size: var(--t-sm); margin-block: 1.5rem; }
.stage-details { border-block: 1px solid var(--p-line-strong); }
.review-heading { display: flex; align-items: center; justify-content: space-between; gap: 1.5rem; margin-bottom: .75rem; }
.simulation-label { margin: 0; flex-shrink: 0; border: 1px solid var(--p-line-strong); padding: .375rem .625rem; }
.review-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1.5rem; margin-block: 1.5rem; }
.wide { grid-column: 1 / -1; }
.review-people { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 1.5rem; padding-bottom: 1.5rem; }
.review-people section { min-width: 0; }
.person-detail { border-top: 1px solid var(--p-line-strong); }
.person-detail summary { color: var(--p-ink); font-family: var(--p-font-body); font-size: var(--t-sm); font-weight: 500; letter-spacing: 0; }
.person-detail summary span { display: block; padding-left: 1rem; color: var(--p-ink-3); font-size: var(--t-xs); font-weight: 400; }
.person-detail label { margin-block: .75rem 1.5rem; }
.documented-ideas { font-size: var(--t-sm); color: var(--p-ink-3); }
.scenario-basis { margin-block: 1.5rem; font-size: var(--t-sm); }
ul { max-width: 65ch; margin: .5rem 0 0; padding-left: 1.25rem; line-height: 1.7; }
.review-problems { color: var(--p-error); font-size: var(--t-sm); margin-bottom: 1.5rem; }
.handoff { display: flex; align-items: center; gap: 1.5rem; flex-wrap: wrap; }
.handoff p { font-size: var(--t-sm); max-width: 38ch; color: var(--p-ink-3); }
.advanced-control { padding-top: 1.5rem; border-top: 1px solid var(--p-line-strong); margin-top: 1.5rem; }
.advanced-control .text-button { margin-inline-start: -12px; }
.advanced-control p, .draft-note { color: var(--p-ink-3); font-size: var(--t-xs); }
.advanced-builder { margin-top: 1.5rem; }
.draft-note { margin-top: 1.5rem; }
.count { font-variant-numeric: tabular-nums; }
@media (max-width: 640px) {
  .brief-form { padding: 1.5rem 1rem; }
  .oracle-heading { gap: .75rem; }
  .oracle-mark { width: 2rem; flex-basis: 2rem; }
  .review-grid, .review-people { grid-template-columns: 1fr; }
  .dictation-line { flex-wrap: wrap; gap: .5rem; }
  .handoff { gap: .75rem; }
  .review-heading { align-items: flex-start; gap: .75rem; }
  .ask-actions p { flex-basis: 100%; }
  input, select, textarea,
  .advanced-builder :deep(input:not([type='checkbox']):not([type='radio'])),
  .advanced-builder :deep(select),
  .advanced-builder :deep(textarea) { font-size: 16px; }
}
</style>
