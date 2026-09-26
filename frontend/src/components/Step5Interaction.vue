<template>
  <section ref="rootRef" class="symposium" :class="{ 'crowd-mode': mode === 'crowd', asleep: cityState === 'asleep' }">
    <!-- The room's caption. -->
    <header class="room-head">
      <span class="p-eyebrow">{{ t('step5.symposium.room') }}</span>
      <h2 class="room-title">{{ t('step5.symposium.whoIsHere') }}</h2>
    </header>

    <!-- The room itself, the painted andron in lamplight: the Scribe at the head of the table, the
         citizens on the couches, those who stood for on one side and those who stood against on the
         other. On phones the couches become one strip of faces to swipe through. -->
    <div class="room-stage">
      <div class="room-scene" aria-hidden="true"></div>
      <p class="room-hint">{{ mode === 'crowd' ? t('step5.symposium.chooseCrowd') : t('step5.symposium.chooseSeat') }}</p>

      <div class="room-faces">
        <div class="seat-head">
          <button
            type="button"
            class="seat scribe"
            :class="{ seated: scribeSeated }"
            :aria-pressed="mode === 'chat' ? scribeSeated : undefined"
            aria-labelledby="seat-scribe-name seat-scribe-note"
            @click="sitWithScribe"
          >
            <span class="seat-coin">
              <CitizenCoin :name="t('step5.symposium.scribe')" :portrait="SCRIBE_PORTRAIT" color="var(--p-gold)" :size="faceSize" />
            </span>
            <span id="seat-scribe-name" class="seat-name">{{ t('step5.symposium.scribe') }}</span>
            <span id="seat-scribe-note" class="seat-note" :class="{ lit: scribeSeated }">{{ scribeNote }}</span>
          </button>
        </div>

        <div
          v-for="wing in wings"
          :key="wing.key"
          class="wing"
          :class="[`is-${wing.key}`, `at-${wing.area}`]"
          role="group"
          :aria-label="wing.label || t('step5.symposium.couches')"
        >
          <span v-if="wing.label" class="wing-label" aria-hidden="true">
            <span class="stance-pip"></span>{{ wing.label }}<span class="wing-n">{{ wing.items.length }}</span>
          </span>
          <ul class="wing-faces" role="list">
            <li v-for="citizen in wing.items" :key="citizen.key">
              <button
                type="button"
                class="seat"
                :class="{ seated: isSeated(citizen), chosen: mode === 'crowd' && selectedAgents.has(citizen.idx) }"
                :aria-pressed="mode === 'crowd' ? selectedAgents.has(citizen.idx) : isSeated(citizen)"
                :aria-labelledby="`seat-${citizen.idx}-name seat-${citizen.idx}-note`"
                :aria-describedby="`seat-${citizen.idx}-desc`"
                @click="mode === 'crowd' ? toggleAgentSelection(citizen.idx) : sitWith(citizen, citizen.idx)"
              >
                <span class="seat-coin" :class="citizen.stance ? `is-${citizen.stance.key}` : null">
                  <CitizenCoin
                    :name="citizen.name"
                    :type="citizen.type"
                    :color="citizen.color"
                    :portrait="citizen.portrait"
                    :size="faceSize"
                  />
                  <span v-if="citizen.stance" class="coin-pip" aria-hidden="true"></span>
                </span>
                <span :id="`seat-${citizen.idx}-name`" class="seat-name">{{ citizen.name }}</span>
                <span :id="`seat-${citizen.idx}-note`" class="seat-note lit">{{ seatNote(citizen) }}</span>
                <span :id="`seat-${citizen.idx}-desc`" class="sr-only">{{ seatDescription(citizen) }}</span>
              </button>
            </li>
          </ul>
        </div>
      </div>

      <!-- What the couches stood for or against: the question put to the city, once. -->
      <div v-if="matter" class="room-matter">
        <span class="p-eyebrow">{{ t('step5.symposium.theQuestion') }}</span>
        <p class="matter-text">{{ matter }}</p>
      </div>
    </div>

    <!-- Who is here tonight, whether the city is awake. -->
    <div class="room-state">
      <p class="room-line">{{ companyLine }}</p>
      <p class="city-state" :class="`is-${cityState}`" role="status">
        <span class="city-lamp" aria-hidden="true"></span>
        <span>{{ cityLine }}</span>
      </p>
      <p v-if="portraitStatus === 'running'" class="painters">{{ t('step5.symposium.painters') }}</p>
    </div>

    <!-- The two doors out of the ordinary conversation. -->
    <div class="room-actions">
      <button
        type="button"
        class="p-button secondary"
        :aria-pressed="mode === 'crowd'"
        @click="toggleCrowdMode"
      >{{ mode === 'crowd' ? t('step5.symposium.backToTable') : t('step5.symposium.askCrowd') }}</button>
      <button
        ref="chronicleToggle"
        type="button"
        class="p-button secondary"
        :aria-expanded="chronicleOpen"
        aria-controls="chronicle-drawer"
        @click="openChronicle"
      >{{ t('step5.symposium.readChronicle') }}</button>
    </div>

    <!-- The table: one conversation, staged as dialogue under the seated face. -->
    <div v-if="mode === 'chat'" ref="tableRef" class="table">
      <Transition name="seat">
        <div :key="seatKey" class="table-band" :style="{ '--role': companion ? companion.ring : 'var(--p-gold)' }">
          <div class="band-face">
            <CitizenCoin
              v-if="companion"
              :name="companion.name"
              :type="companion.type"
              :color="companion.color"
              :portrait="companion.portrait"
              size="xl"
            />
            <CitizenCoin v-else :name="t('step5.symposium.scribe')" :portrait="SCRIBE_PORTRAIT" color="var(--p-gold)" size="xl" />
          </div>
          <div class="band-text">
            <span class="p-eyebrow">{{ t('step5.symposium.seatedWith') }}</span>
            <h3 class="band-name" tabindex="-1">{{ companion ? companion.name : t('step5.symposium.scribe') }}</h3>
            <p class="band-role">{{ companion ? companion.role : t('step5.symposium.scribeRole') }}</p>
            <p v-if="companion && companion.stance" class="stance band-stance" :class="`is-${companion.stance.key}`">
              <span class="stance-pip" aria-hidden="true"></span>{{ companion.stance.text }}
            </p>
            <blockquote v-if="companion && companion.quote" class="band-quote">
              <p>{{ companion.quote.text }}</p>
              <cite>{{ t(`step5.symposium.saidIn.${companion.quote.place}`) }}</cite>
            </blockquote>
            <p v-else-if="companion" class="band-line">{{ companion.line }}</p>
            <div v-else class="band-saw">
              <span class="saw-label">{{ t('step5.symposium.scribeSaw') }}</span>
              <p class="band-line">{{ scribeSawFull }}</p>
            </div>
          </div>
        </div>
      </Transition>
      <div class="p-meander table-rule" aria-hidden="true"></div>

      <ol class="dialogue" role="log" aria-live="polite" aria-relevant="additions">
        <li v-if="chatHistory.length === 0 && !isSending && !(cityState === 'asleep' && chatTarget === 'agent')" class="dialogue-empty">
          <p>{{ chatTarget === 'report_agent' ? t('step5.symposium.emptyScribe') : t('step5.symposium.emptyCitizen', { name: companion ? companion.name : '' }) }}</p>
        </li>
        <li
          v-for="(msg, idx) in chatHistory"
          :key="idx"
          class="line"
          :class="msg.role === 'user' ? 'asked' : 'answered'"
        >
          <template v-if="msg.role === 'user'">
            <span class="p-eyebrow asked-label">{{ t('step5.symposium.youAsked') }}</span>
            <p class="asked-text">{{ msg.content }}</p>
          </template>
          <template v-else>
            <CitizenCoin
              v-if="companion"
              class="line-face"
              :name="companion.name"
              :type="companion.type"
              :color="companion.color"
              :portrait="companion.portrait"
              size="md"
            />
            <CitizenCoin v-else class="line-face" :name="t('step5.symposium.scribe')" :portrait="SCRIBE_PORTRAIT" color="var(--p-gold)" size="md" />
            <div class="answered-body">
              <span class="line-meta">
                <span class="line-who">{{ speakerName }}</span>
                <button
                  v-if="canHear"
                  type="button"
                  class="hear"
                  :class="{ speaking: speakingKey === `chat-${idx}` }"
                  :data-hear="`chat-${idx}`"
                  :aria-pressed="speakingKey === `chat-${idx}` ? 'true' : 'false'"
                  :aria-label="t('step5.symposium.hear', { name: speakerName })"
                  :aria-describedby="hearNote.key === `chat-${idx}` ? `hear-note-chat-${idx}` : undefined"
                  @click="hear(`chat-${idx}`, msg.content, chatSpeaker())"
                >
                  <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                    <path d="M3.5 7.5h3l4-3.5v12l-4-3.5h-3z" />
                    <path v-if="speakingKey !== `chat-${idx}`" d="M13.5 7a4 4 0 0 1 0 6M15.6 5a7 7 0 0 1 0 10" />
                    <path v-else d="M13.5 8l4 4M17.5 8l-4 4" />
                  </svg>
                </button>
              </span>
              <div v-if="speakingKey === `chat-${idx}` || hearNote.key === `chat-${idx}`" class="voicing" :data-voicing="`chat-${idx}`">
                <template v-if="speakingKey === `chat-${idx}`">
                  <span class="voicing-state" :class="`is-${hearPhase}`">
                    <span class="voice-bars" aria-hidden="true"><i></i><i></i><i></i></span>
                    {{ hearPhase === 'speaking' ? t('step5.symposium.hearing.speaking') : t('step5.symposium.hearing.gathering') }}
                  </span>
                  <button type="button" class="p-button secondary small voicing-stop" @click="stopFrom(`chat-${idx}`)"><span class="stop-mark" aria-hidden="true"></span>{{ t('step5.symposium.hearing.stop') }}</button>
                </template>
                <p v-if="hearNote.key === `chat-${idx}`" :id="`hear-note-chat-${idx}`" class="voicing-note">{{ hearNote.text }}</p>
              </div>
              <div class="answered-text" v-html="renderMarkdown(msg.content)"></div>
            </div>
          </template>
        </li>
        <li v-if="isSending" class="line answered thinking">
          <CitizenCoin
            v-if="companion"
            class="line-face"
            :name="companion.name"
            :type="companion.type"
            :color="companion.color"
            :portrait="companion.portrait"
            size="md"
          />
          <CitizenCoin v-else class="line-face" :name="t('step5.symposium.scribe')" :portrait="SCRIBE_PORTRAIT" color="var(--p-gold)" size="md" />
          <div class="answered-body">
            <span class="line-meta"><span class="line-who working">{{ workingText }}</span></span>
            <span class="ellipsis" aria-hidden="true"><i></i><i></i><i></i></span>
          </div>
        </li>
      </ol>

      <div class="prompt" :class="{ stuck: chatHistory.length > 0 }">
        <p v-if="cityState === 'asleep' && chatTarget === 'agent'" class="asleep-note" role="status">
          <span>{{ t('step5.symposium.asleepCitizen', { name: companion ? companion.name : '' }) }}</span>
          <button type="button" class="p-button secondary tall" @click="sitWithScribe">{{ t('step5.symposium.sitWithScribe') }}</button>
        </p>

        <!-- Socratic questions: they are placed in the mouth, not sent. -->
        <div
          v-if="Array.isArray(socraticPrompts)"
          class="socratic"
          role="group"
          aria-labelledby="socratic-label"
        >
          <span id="socratic-label" class="p-eyebrow socratic-label">{{ t('step5.socraticLabel') }}</span>
          <div class="socratic-chips">
            <button
              v-for="(q, qIdx) in socraticPrompts"
              :key="qIdx"
              type="button"
              class="socratic-chip"
              :disabled="isChatInputDisabled"
              @click="insertSocraticPrompt(q)"
            >{{ q }}</button>
          </div>
        </div>

        <form class="ask" @submit.prevent="sendMessage">
          <label class="sr-only" for="symposium-ask">{{ chatTarget === 'report_agent' ? t('step5.symposium.placeholderScribe') : t('step5.symposium.placeholder') }}</label>
          <textarea
            id="symposium-ask"
            ref="chatInputRef"
            v-model="chatInput"
            class="ask-input"
            :placeholder="chatTarget === 'report_agent' ? t('step5.symposium.placeholderScribe') : t('step5.symposium.placeholder')"
            rows="1"
            :disabled="isChatInputDisabled"
            @keydown.enter.exact.prevent="sendMessage"
            @input="growInput"
          ></textarea>
          <button
            type="submit"
            class="p-button ask-send"
            :disabled="!chatInput.trim() || isChatInputDisabled"
          >{{ isSending ? t('step5.symposium.sending') : t('step5.symposium.send') }}</button>
        </form>
      </div>
    </div>

    <!-- The crowd: one question, many voices, answered as a quorum of faces. -->
    <div v-else ref="tableRef" class="table crowd">
      <div class="crowd-head">
        <span class="p-eyebrow">{{ t('step5.symposium.askCrowd') }}</span>
        <h3 class="band-name">{{ t('step5.symposium.crowdTitle') }}</h3>
        <p class="band-line">{{ t('step5.symposium.crowdHint') }}</p>
      </div>
      <div class="p-meander table-rule" aria-hidden="true"></div>

      <div class="crowd-pick">
        <p class="crowd-count" aria-live="polite">{{ crowdCountLine }}</p>
        <div class="crowd-links">
          <button type="button" class="p-button ghost tall" :disabled="!citizens.length" @click="selectAllAgents">{{ t('step5.symposium.everyone') }}</button>
          <button type="button" class="p-button ghost tall" :disabled="!selectedAgents.size" @click="clearAgentSelection">{{ t('step5.symposium.noOne') }}</button>
        </div>
      </div>
      <ul v-if="chosenCitizens.length" class="faces" role="list" :aria-label="t('step5.symposium.chooseCrowd')">
        <li v-for="c in chosenCitizens" :key="c.key" class="face">
          <CitizenCoin :name="c.name" :type="c.type" :color="c.color" :portrait="c.portrait" size="sm" />
          <span class="face-name">{{ c.name }}</span>
        </li>
      </ul>

      <form class="ask crowd-ask" @submit.prevent="submitSurvey">
        <label class="sr-only" for="symposium-crowd">{{ t('step5.symposium.crowdPlaceholder') }}</label>
        <textarea
          id="symposium-crowd"
          v-model="surveyQuestion"
          class="ask-input"
          :placeholder="t('step5.symposium.crowdPlaceholder')"
          rows="2"
          :readonly="isSurveying"
          :disabled="!cityAwake"
        ></textarea>
        <div class="crowd-submit">
          <!-- Never natively disabled: the button keeps focus while the crowd answers. -->
          <button
            type="submit"
            class="p-button"
            :aria-disabled="canAskCrowd ? undefined : 'true'"
            :aria-describedby="crowdReason ? 'crowd-reason' : undefined"
          >{{ isSurveying ? t('step5.symposium.crowdAnswering') : t('step5.symposium.askTheCrowd') }}</button>
          <span v-if="crowdReason" id="crowd-reason" class="ask-reason">{{ crowdReason }}</span>
        </div>
      </form>

      <!-- Said once, politely, when the answers are in and again when the Scribe has read them. -->
      <p class="sr-only" role="status" aria-live="polite">{{ quorumAnnouncement }}</p>

      <div v-if="isSurveying" class="quorum-waiting" role="status">
        <ul class="q-waiting-faces" role="list">
          <li v-for="c in chosenCitizens.slice(0, 18)" :key="`wait-${c.key}`">
            <CitizenCoin :name="c.name" :type="c.type" :color="c.color" :portrait="c.portrait" size="sm" />
          </li>
        </ul>
        <span class="ask-reason">{{ t('step5.symposium.crowdAnswering') }}</span>
        <span class="ellipsis" aria-hidden="true"><i></i><i></i><i></i></span>
      </div>

      <section v-if="surveyResults.length" class="quorum" :aria-label="t('step5.symposium.quorum.title')">
        <span class="p-eyebrow">{{ readingState === 'done' ? t('step5.symposium.quorum.reading') : t('step5.symposium.answers') }}</span>
        <h4 class="quorum-summary">{{ quorumHeadline }}</h4>
        <p v-if="quorumSubline" class="quorum-sub" :class="{ pending: readingState === 'reading' }">
          {{ quorumSubline }}<span v-if="readingState === 'reading'" class="ellipsis inline" aria-hidden="true"><i></i><i></i><i></i></span>
        </p>
        <p class="answers-question">{{ surveyResults[0].question }}</p>

        <div v-if="quorumGroups.length > 1" class="tally" role="img" :aria-label="`${t('step5.symposium.quorum.tally')}: ${quorumTallyWords}`">
          <span
            v-for="g in quorumGroups"
            :key="`bar-${g.key}`"
            class="tally-part"
            :class="`is-${g.key}`"
            :style="{ flexGrow: g.items.length }"
          ></span>
        </div>

        <div class="q-groups">
          <div v-for="g in quorumGroups" :key="g.key" class="q-group" :class="`is-${g.key}`">
            <span class="q-group-label"><span class="stance-pip" aria-hidden="true"></span>{{ g.label }} <span class="q-group-n">{{ g.items.length }}</span></span>
            <ul class="q-faces" role="list">
              <li v-for="r in g.items" :key="`q-${r.agent_id}`">
                <button
                  type="button"
                  class="q-face"
                  :data-agent="r.agent_id"
                  :tabindex="activeAnswer && activeAnswer.agent_id === r.agent_id ? 0 : -1"
                  :aria-pressed="!!activeAnswer && activeAnswer.agent_id === r.agent_id"
                  :aria-label="t('step5.symposium.quorum.faceLabel', { name: r.name, group: g.label })"
                  aria-controls="quorum-voice"
                  @mouseenter="quorumActive = r.agent_id"
                  @focus="quorumActive = r.agent_id"
                  @click="pickFace(r.agent_id)"
                  @keydown="onQuorumKey($event, r.agent_id)"
                >
                  <CitizenCoin :name="r.name" :type="r.type" :color="r.color" :portrait="portraitOf(r)" size="lg" />
                  <span class="q-name" :class="{ long: !isPersonName(r) }">{{ shortName(r) }}</span>
                </button>
              </li>
            </ul>
          </div>
        </div>
        <p class="q-hint">{{ t('step5.symposium.quorum.hint') }}</p>

        <article v-if="activeAnswer" id="quorum-voice" class="q-voice" :style="{ '--role': activeAnswer.ring }">
          <CitizenCoin :name="activeAnswer.name" :type="activeAnswer.type" :color="activeAnswer.color" :portrait="portraitOf(activeAnswer)" size="md" />
          <div class="answered-body">
            <span class="line-meta">
              <span class="line-who">{{ activeAnswer.name }}</span>
              <button
                v-if="canHear && activeAnswer.spoke"
                type="button"
                class="hear"
                :class="{ speaking: speakingKey === `q-${activeAnswer.agent_id}` }"
                :data-hear="`q-${activeAnswer.agent_id}`"
                :aria-pressed="speakingKey === `q-${activeAnswer.agent_id}` ? 'true' : 'false'"
                :aria-label="t('step5.symposium.hear', { name: activeAnswer.name })"
                :aria-describedby="hearNote.key === `q-${activeAnswer.agent_id}` ? `hear-note-q-${activeAnswer.agent_id}` : undefined"
                @click="hear(`q-${activeAnswer.agent_id}`, activeAnswer.answer, crowdSpeaker(activeAnswer))"
              >
                <svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true">
                  <path d="M3.5 7.5h3l4-3.5v12l-4-3.5h-3z" />
                  <path v-if="speakingKey !== `q-${activeAnswer.agent_id}`" d="M13.5 7a4 4 0 0 1 0 6M15.6 5a7 7 0 0 1 0 10" />
                  <path v-else d="M13.5 8l4 4M17.5 8l-4 4" />
                </svg>
              </button>
            </span>
            <div v-if="speakingKey === `q-${activeAnswer.agent_id}` || hearNote.key === `q-${activeAnswer.agent_id}`" class="voicing" :data-voicing="`q-${activeAnswer.agent_id}`">
              <template v-if="speakingKey === `q-${activeAnswer.agent_id}`">
                <span class="voicing-state" :class="`is-${hearPhase}`">
                  <span class="voice-bars" aria-hidden="true"><i></i><i></i><i></i></span>
                  {{ hearPhase === 'speaking' ? t('step5.symposium.hearing.speaking') : t('step5.symposium.hearing.gathering') }}
                </span>
                <button type="button" class="p-button secondary small voicing-stop" @click="stopFrom(`q-${activeAnswer.agent_id}`)"><span class="stop-mark" aria-hidden="true"></span>{{ t('step5.symposium.hearing.stop') }}</button>
              </template>
              <p v-if="hearNote.key === `q-${activeAnswer.agent_id}`" :id="`hear-note-q-${activeAnswer.agent_id}`" class="voicing-note">{{ hearNote.text }}</p>
            </div>
            <p v-if="activeAnswer.role" class="q-role">{{ activeAnswer.role }}</p>
            <p v-if="activeAnswer.stance" class="stance" :class="`is-${activeAnswer.stance.key}`"><span class="stance-pip" aria-hidden="true"></span>{{ activeAnswer.stance.text }}</p>
            <div class="answered-text" v-html="renderMarkdown(activeAnswer.answer)"></div>
          </div>
        </article>

        <button
          type="button"
          class="p-button ghost tall read-all"
          :aria-expanded="allAnswersOpen"
          aria-controls="quorum-all"
          @click="allAnswersOpen = !allAnswersOpen"
        >{{ allAnswersOpen ? t('step5.symposium.quorum.foldAll') : t('step5.symposium.quorum.readAll') }}</button>
        <ul v-if="allAnswersOpen" id="quorum-all" class="reply-list" role="list">
          <li v-for="r in surveyResults" :key="`reply-${r.agent_id}`" class="reply">
            <CitizenCoin :name="r.name" :type="r.type" :color="r.color" :portrait="portraitOf(r)" size="md" />
            <div class="answered-body">
              <span class="line-meta"><span class="line-who">{{ r.name }}</span></span>
              <p v-if="r.role" class="q-role">{{ r.role }}</p>
              <div class="answered-text" v-html="renderMarkdown(r.answer)"></div>
            </div>
          </li>
        </ul>
      </section>
    </div>

    <!-- The voice the answers are heard in: silent until a hear button is pressed. -->
    <audio ref="voiceRef" class="voice-audio" preload="auto"></audio>
    <p class="sr-only" role="status" aria-live="polite">{{ hearAnnouncement }}</p>

    <!-- The Chronicle, held up in the dark: a page of parchment that slides in from the side. -->
    <Teleport to="body">
      <Transition name="drawer">
        <div v-if="chronicleOpen" class="drawer-root">
          <div class="drawer-backdrop" aria-hidden="true" @click="closeChronicle"></div>
          <aside
            id="chronicle-drawer"
            class="chronicle p-paper"
            role="dialog"
            aria-modal="true"
            :aria-label="t('step5.symposium.chronicle')"
            @keydown.esc.prevent="closeChronicle"
            @keydown.tab="trapFocus"
          >
            <div class="chronicle-bar">
              <span class="p-eyebrow">Δ΄ · {{ t('step5.symposium.chronicle') }}</span>
              <button ref="chronicleClose" type="button" class="p-button ghost tall" @click="closeChronicle">{{ t('step5.symposium.closeChronicle') }}</button>
            </div>
            <div class="chronicle-page">
              <template v-if="reportOutline">
                <h1 class="chronicle-title">{{ reportOutline.title }}</h1>
                <p v-if="reportOutline.summary" class="chronicle-summary">{{ reportOutline.summary }}</p>
                <div v-if="question" class="chronicle-question">
                  <span class="p-eyebrow">{{ t('step5.symposium.theQuestion') }}</span>
                  <p>{{ question }}</p>
                </div>
                <div class="p-meander chronicle-rule" aria-hidden="true"></div>
                <article v-for="(section, idx) in reportOutline.sections" :key="idx" class="chapter">
                  <span class="p-eyebrow">{{ t('step5.symposium.chapter') }} {{ greekNumeral(idx + 1) }}</span>
                  <h2 class="chapter-title">{{ section.title }}</h2>
                  <div v-if="generatedSections[idx + 1]" class="chapter-body" v-html="renderMarkdown(generatedSections[idx + 1])"></div>
                  <p v-else class="chapter-pending">{{ t('step5.symposium.chapterPending') }}</p>
                </article>
              </template>
              <p v-else class="chronicle-waiting">{{ t('step5.symposium.chronicleWaiting') }}</p>
              <router-link v-if="reportId" class="p-button secondary chronicle-link" :to="{ name: 'Report', params: { reportId } }">{{ t('step5.symposium.openChronicleAct') }}</router-link>
            </div>
          </aside>
        </div>
      </Transition>
    </Teleport>
  </section>
</template>

<script setup>
// Act Ε΄, the Symposium: a room with faces. The painted andron stands behind
// the couches; the Scribe sits at the head, the citizens recline on either side
// by where they stood, and the question put to the city hangs between them.
// Sitting down brings the table: the seated face, their stance and one line of
// their own from the Agora or the Stoa, and the conversation set as a script.
// Or the visitor puts one question to the crowd and the answers come back as a
// quorum of faces. Every
// call the old workbench made (chat with the Scribe, interviews, the
// Chronicle's pages, the citizens' profiles) is kept; the room around them is new.
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import CitizenCoin from './CitizenCoin.vue'
import { chatWithReport, getReport, getAgentLog } from '../api/report'
import {
  interviewAgents,
  getSimulationProfilesRealtime,
  getEnvStatus,
  getSimulationConfig,
  getSimulationPosts
} from '../api/simulation'
import { citizenName, entityTypeName, roleFamily, roleLabel, roleColorVar, ROLE_COLOR_VAR, voiceOf as voiceForType } from '../parthenon/vocabulary.js'
import { useCitizenPortraits } from '../parthenon/portraits.js'
import { speakWords, filmAssetUrl, getCitizenStances } from '../api/parthenon'

const { t, tm, locale } = useI18n()

const props = defineProps({
  reportId: String,
  simulationId: String
})

const emit = defineEmits(['add-log', 'update-status'])

// Room state
const mode = ref('chat') // chat | crowd
const chatTarget = ref('report_agent') // report_agent | agent
const selectedAgent = ref(null)
const selectedAgentIndex = ref(null)
// Whether the citizens can be questioned: they are present only while the city is awake.
const cityState = ref('unknown') // unknown | awake | asleep
const cityAwake = computed(() => cityState.value !== 'asleep')

// Chat state
const chatInput = ref('')
const chatHistory = ref([])
const chatHistoryCache = ref({}) // { report_agent: [], agent_0: [], ... }
const isSending = ref(false)
const chatInputRef = ref(null)

// Crowd state
const selectedAgents = ref(new Set())
const surveyQuestion = ref('')
const surveyResults = ref([])
const isSurveying = ref(false)
const quorumActive = ref(null)
const allAnswersOpen = ref(false)
const quorumReading = ref('')
const readingState = ref('idle') // idle | reading | done | failed

// The Chronicle
const reportOutline = ref(null)
const generatedSections = ref({})
const question = ref('')
const profiles = ref([])
const chronicleOpen = ref(false)
const chronicleToggle = ref(null)
const chronicleClose = ref(null)
const rootRef = ref(null)

// Where each citizen stood, and what they said in the square.
const agentConfigs = ref([])
const voices = ref({}) // agent id -> { text, place: 'agora' | 'stoa' }
// Where each citizen ended, when the Scribe has read the argument (the same
// reading the Agora shows as "Who moved"), so both rooms seat them alike.
const endings = ref({}) // agent id -> { final_stance, moved }

const loadEndings = async () => {
  if (!props.simulationId) return
  try {
    const res = await getCitizenStances(props.simulationId)
    const data = res?.data
    if (data?.status !== 'completed') return
    const map = {}
    for (const c of data.citizens || []) {
      if (c && c.agent_id !== undefined && c.agent_id !== null && c.final_stance) {
        map[String(c.agent_id)] = { final_stance: c.final_stance, moved: !!c.moved }
      }
    }
    endings.value = map
  } catch {
    // No reading yet: the room seats them where they began.
  }
}
// The gathering's id can arrive after the room opens (it comes with the Chronicle).
watch(() => props.simulationId, () => loadEndings(), { immediate: true })

// Faces: read only here; the Gathering is where the painters are called.
const simulationIdRef = computed(() => props.simulationId || null)
const { status: portraitStatus, portraitFor } = useCitizenPortraits(simulationIdRef)

// Narrow rooms (phones and small tablets): the couches become one strip of
// faces under the threshold, so the table is never far below.
const NARROW = '(max-width: 1023px)'
const narrowQuery = typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(NARROW) : null
const isNarrow = ref(narrowQuery ? narrowQuery.matches : false)
const onNarrowChange = (e) => { isNarrow.value = e.matches }
const faceSize = computed(() => (isNarrow.value ? 'lg' : 'xl'))
const tableRef = ref(null)

// The Scribe's own face, painted once by the same painters as the citizens.
const SCRIBE_PORTRAIT = '/media/symposium/scribe.jpg'

const socraticPrompts = computed(() => tm('step5.socraticPrompts'))

// Words for small numbers: the city counts in words.
const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen', 'twenty']
const inWords = (n) => (n >= 0 && n < WORDS.length ? WORDS[n] : String(n))
const capital = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s)
const GREEK = ['Α΄', 'Β΄', 'Γ΄', 'Δ΄', 'Ε΄', 'Ϛ΄', 'Ζ΄', 'Η΄', 'Θ΄', 'Ι΄', 'ΙΑ΄', 'ΙΒ΄']
const greekNumeral = (n) => GREEK[n - 1] || String(n)
const joinList = (items) => {
  try {
    return new Intl.ListFormat(String(locale.value || 'en').startsWith('zh') ? 'zh' : 'en', { style: 'long', type: 'conjunction' }).format(items)
  } catch {
    return items.join(', ')
  }
}

// A citizen as the room sees them: a name without a suffix, a role in words,
// where they stood, one line of their own, and the colour of their family.
const ACCOUNT_PREFIX = /^(this is )?(the )?(official )?(civic |public |municipal )?(account|channel|office|desk|page|profile|biography)( biography)?( for the public channel)?( of)?\s*/i
const familyOf = (name, profession) => {
  const text = `${name} ${profession}`
  if (/\b(campaign|movement|coalition)\b/i.test(text)) return 'movements'
  if (/\b(compute|company|firm|corporation|council|cooperative|association|secretariat|school|ministry|outlet|agency|authority)\b/i.test(text)) return 'institutions'
  return roleFamily(profession)
}
const roleLine = (p) => {
  const raw = String(p.profession || '').trim()
  if (raw) return capital(raw.split(/[,;(]/)[0].trim())
  const typed = entityTypeName(p.entity_type || p.type)
  return typed ? capital(typed) : ''
}
const escapeRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const bioLine = (p, name) => {
  let text = String(p.bio || p.persona || '').replace(/\s+/g, ' ').trim()
  text = text.replace(ACCOUNT_PREFIX, '')
  if (name) text = text.replace(new RegExp(`^(the )?${escapeRe(name)}\\s*(,|:|is|was)?\\s*`, 'i'), '')
  const first = text.split(/(?<=[.!?])\s+/)[0] || ''
  return capital(first.length > 160 ? `${first.slice(0, 157).replace(/\s+\S*$/, '')}...` : first)
}
// "CitizenJury" is the engine's spelling; the room says "Citizen Jury".
const spacedName = (s) => (/^[A-Z][a-z]+(?:[A-Z][a-z]+)+$/.test(String(s || '')) ? String(s).replace(/([a-z])([A-Z])/g, '$1 $2') : s)
const nameKey = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
// A face in the quorum carries a first name for a person, the whole name for a body.
const BODY_WORDS = /\b(campaign|association|cooperative|council|company|compute|coalition|movement|party|union|office|ministry|school|church|priests|seers|jurors|jury|sophists|fishermen|for|of)\b/i
const isPersonName = (r) => {
  const name = String(r?.name || '').trim()
  if (!name || /^the\s/i.test(name)) return false
  if (r?.type && roleFamily(r.type) !== 'people') return false
  if (BODY_WORDS.test(name)) return false
  return name.split(/\s+/).length <= 4
}
const shortName = (r) => {
  const name = String(r?.name || '').trim()
  if (!isPersonName(r)) return name.replace(/^the\s+/i, '')
  const n = name.replace(/^(dr\.?|father|mother|saint|st\.?)\s+/i, '')
  return n.split(/\s+/)[0] || n
}

// Where they stood, in words: the stance they came with and how hard they held it.
const stanceOf = (cfg) => {
  const raw = String(cfg?.stance || '').toLowerCase().trim()
  if (!raw) return null
  const bias = Number(cfg?.sentiment_bias)
  const b = Number.isFinite(bias) ? bias : 0
  let key = 'between'
  let words = 'between'
  if (/^(support|pro|for|favo)/.test(raw)) {
    key = 'for'
    words = b >= 0.7 ? 'forFirm' : b > 0 && b < 0.35 ? 'leanFor' : 'for'
  } else if (/^(oppos|against|anti|reject)/.test(raw)) {
    key = 'against'
    words = b <= -0.7 ? 'againstFirm' : b < 0 && b > -0.35 ? 'leanAgainst' : 'against'
  } else if (/^(observ|watch|bystand)/.test(raw)) {
    key = 'aside'
    words = 'aside'
  }
  return { key, text: t(`step5.symposium.stance.${words}`) }
}

// Where they ended: a citizen who moved is seated on their new side without the
// firmness of where they began; one who did not keeps their own words.
const stanceAt = (cfg, ending) => {
  if (!ending || !ending.moved) return stanceOf(cfg)
  const final = String(ending.final_stance || '').toLowerCase()
  const bias = /^(support|pro|for|favo)/.test(final) ? 0.5 : /^(oppos|against|anti|reject)/.test(final) ? -0.5 : 0
  return stanceOf({ stance: final, sentiment_bias: bias })
}

// One line of their own speech: the most substantial thing they said in the
// Agora or the Stoa, without handles, tags or links.
const cleanSpeech = (text) =>
  String(text || '')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/(^|[\s(])[#@][\p{L}\p{N}_]+/gu, '$1')
    .replace(/\s+/g, ' ')
    .replace(/^["“‘\s]+|["”’\s]+$/g, '')
    .trim()
const SENTENCE = /[^.!?。！？]+(?:[.!?。！？]+["”’)]*|$)/g
const FIRST_PERSON = /\b(i|i'm|i've|i'd|i'll|my|me|we|we're|our|us)\b/i
const VERDICT = /\b(should|must|will not|won't|cannot|can't|refuse|never|sign|signing|reject|support|oppose|against|want|believe|demand|vote|choose)\b/i
const BOILER = /^(correction|notice|update|note|reminder|practical notice|hearing note|sunday note|thread|breaking)\b/i
const lineScore = (s, i) => {
  const cjk = /[㐀-鿿]/.test(s)
  const len = cjk ? s.length * 2.5 : s.length
  if (len < 36) return -1
  let score = len <= 180 ? Math.min(len, 140) / 140 : 0.55
  if (FIRST_PERSON.test(s)) score += 0.35
  if (VERDICT.test(s)) score += 0.25
  if (BOILER.test(s)) score -= 0.8
  if (/^[^.:]{1,40}:\s/.test(s)) score -= 0.3
  return score - i * 0.02
}
const bestLineOf = (text) => {
  const sentences = (cleanSpeech(text).match(SENTENCE) || []).map((s) => s.trim()).filter(Boolean)
  const candidates = []
  sentences.forEach((s, i) => {
    candidates.push({ text: s, score: lineScore(s, i) })
    const next = sentences[i + 1]
    if (next && s.length + next.length + 1 <= 160) candidates.push({ text: `${s} ${next}`, score: lineScore(`${s} ${next}`, i) - 0.05 })
  })
  candidates.sort((a, b) => b.score - a.score)
  return candidates[0] || null
}
const trimLine = (s) => capital(s.length > 190 ? `${s.slice(0, 180).replace(/\s+\S*$/, '')}…` : s)
// On a quote, the citizen's own words are the quote; the post they quoted is someone else's.
const ownWords = (post) => (post.original_post_id !== null && post.original_post_id !== undefined ? post.quote_content : post.content) || ''
const postWeight = (post) => {
  const len = Math.min(cleanSpeech(post.words).length, 700)
  const heard = (Number(post.num_likes) || 0) + 2 * (Number(post.num_shares) || 0) - 0.5 * (Number(post.num_dislikes) || 0)
  return len / 700 + 0.25 * Math.log1p(Math.max(0, heard))
}
const voiceOf = (posts) => {
  const ranked = [...posts].sort((a, b) => postWeight(b) - postWeight(a))
  let fallback = null
  for (const post of ranked.slice(0, 6)) {
    const best = bestLineOf(post.words)
    if (!best) continue
    if (best.score >= 0.45) return { text: trimLine(best.text), place: post.place }
    if (!fallback || best.score > fallback.score) fallback = { ...best, place: post.place }
  }
  return fallback && fallback.score > -0.5 ? { text: trimLine(fallback.text), place: fallback.place } : null
}

const configById = computed(() => {
  const out = {}
  for (const a of agentConfigs.value) if (a && a.agent_id !== undefined && a.agent_id !== null) out[String(a.agent_id)] = a
  return out
})
const configByName = computed(() => {
  const out = {}
  for (const a of agentConfigs.value) if (a && a.entity_name) out[nameKey(a.entity_name)] = a
  return out
})

const citizens = computed(() =>
  profiles.value.map((p, idx) => {
    const agentId = Number.isInteger(p.user_id) ? p.user_id : idx
    const cfg = configById.value[String(agentId)] || configByName.value[nameKey(p.name)] || null
    const name = spacedName(citizenName(p.name, p.username)) || `Citizen ${idx + 1}`
    const profession = String(p.profession || '')
    const type = String(cfg?.entity_type || p.entity_type || '')
    // The engine's type decides the colour, as in every other act; without one, the profession does.
    const color = type ? '' : ROLE_COLOR_VAR[familyOf(name, profession)] || ROLE_COLOR_VAR.people
    return {
      key: p.user_id ?? p.username ?? idx,
      idx,
      agentId,
      name,
      type,
      color,
      ring: color || roleColorVar(type),
      role: roleLine(p) || roleLabel(type) || t('step2.unknownProfession'),
      line: bioLine(p, name),
      stance: stanceAt(cfg, endings.value[String(agentId)]),
      quote: voices.value[String(agentId)] || null,
      portrait: portraitFor(agentId) || portraitFor(name) || ''
    }
  })
)
const companion = computed(() => (chatTarget.value === 'agent' && selectedAgentIndex.value !== null ? citizens.value[selectedAgentIndex.value] : null))
const chosenCitizens = computed(() => citizens.value.filter((c) => selectedAgents.value.has(c.idx)))
const speakerName = computed(() => (companion.value ? companion.value.name : t('step5.symposium.scribe')))

// The couches, by where their citizens stood: those for on the left, those
// against on the right, those between beneath the Scribe, the watchers at the
// foot. On phones the same order runs along the strip.
const WING_AREA = { for: 'left', between: 'mid', aside: 'foot', none: 'rest', against: 'right' }
const wings = computed(() => {
  const list = citizens.value
  const buckets = { for: [], between: [], aside: [], none: [], against: [] }
  for (const c of list) buckets[c.stance ? c.stance.key : 'none'].push(c)
  if (buckets.none.length === list.length) {
    // Where they stood is not known: the couches fill evenly, left and right, unnamed.
    const half = Math.ceil(list.length / 2)
    return [
      { key: 'left', area: 'left', label: '', items: list.slice(0, half) },
      { key: 'right', area: 'right', label: '', items: list.slice(half) }
    ].filter((w) => w.items.length)
  }
  return Object.keys(WING_AREA)
    .filter((key) => buckets[key].length)
    .map((key) => ({ key, area: WING_AREA[key], label: t(`step5.symposium.wall.${key}`), items: buckets[key] }))
})
const isSeated = (c) => mode.value === 'chat' && chatTarget.value === 'agent' && selectedAgentIndex.value === c.idx
const scribeSeated = computed(() => mode.value === 'chat' && chatTarget.value === 'report_agent')
const scribeNote = computed(() => {
  if (scribeSeated.value) return t('step5.symposium.seated')
  return mode.value === 'crowd' ? t('step5.symposium.scribeListens') : t('step5.symposium.scribeRole')
})
// On the couch a face says only whether it is seated or chosen; the words live at the table.
const seatNote = (c) => {
  if (mode.value === 'crowd') return selectedAgents.value.has(c.idx) ? t('step5.symposium.willAnswer') : ''
  return isSeated(c) ? t('step5.symposium.seated') : ''
}
// What a listener hears after the name: who they are and where they stood.
const seatDescription = (c) => [c.role, c.stance ? c.stance.text : ''].filter(Boolean).join('. ')
const seatKey = computed(() => (companion.value ? `c-${companion.value.idx}` : 'scribe'))

// The question the couches stood for or against: the last question the city was asked.
const matter = computed(() => {
  const q = String(question.value || '').replace(/\s+/g, ' ').trim()
  if (!q) return ''
  const sentences = (q.match(/[^.!?。！？]+(?:[.!?。！？]+["”’)]*|$)/g) || [q]).map((s) => s.trim()).filter(Boolean)
  const asks = sentences.filter((s) => /[?？]["”’)]*$/.test(s))
  const pick = asks.length ? asks[asks.length - 1] : sentences[0] || q
  return pick.length > 220 ? `${pick.slice(0, 210).replace(/\s+\S*$/, '')}…` : pick
})

// The Scribe at the head of the table, with one line about what she saw: the Chronicle's own summary.
const scribeSawFull = computed(() => String(reportOutline.value?.summary || '').replace(/\s+/g, ' ').trim() || t('step5.symposium.scribeLine'))

const companyLine = computed(() => {
  const n = citizens.value.length
  if (!n) return t('step5.symposium.companyScribeOnly')
  if (n === 1) return t('step5.symposium.companyOne')
  return t('step5.symposium.company', { n, w: inWords(n) })
})
const cityLine = computed(() => {
  if (cityState.value === 'awake') return t('step5.symposium.city.awake')
  if (cityState.value === 'asleep') return t('step5.symposium.city.asleep')
  return t('step5.symposium.city.listening')
})
const crowdCountLine = computed(() => {
  const n = selectedAgents.value.size
  if (!n) return t('step5.symposium.crowdNone')
  if (n === 1) return t('step5.symposium.crowdCountOne')
  return capital(t('step5.symposium.crowdCount', { n, w: inWords(n) }))
})
const workingText = computed(() =>
  chatTarget.value === 'report_agent'
    ? t('step5.symposium.scribeWriting')
    : t('step5.symposium.thinking', { name: companion.value ? companion.value.name : '' })
)

const isChatInputDisabled = computed(() =>
  isSending.value || (chatTarget.value === 'agent' && (selectedAgentIndex.value === null || !cityAwake.value))
)
const canAskCrowd = computed(() => cityAwake.value && selectedAgents.value.size > 0 && !!surveyQuestion.value.trim() && !isSurveying.value)
const crowdReason = computed(() => {
  if (isSurveying.value) return ''
  if (!cityAwake.value) return t('step5.symposium.asleep')
  if (!selectedAgents.value.size) return t('step5.symposium.needCrowd')
  if (!surveyQuestion.value.trim()) return t('step5.symposium.needQuestion')
  return ''
})

const addLog = (msg) => emit('add-log', msg)
const setStatus = (status, text = '') => emit('update-status', status, text)
// At rest, the header says whether the city is awake.
const setIdle = () => {
  if (cityState.value === 'awake') setStatus('live', t('step5.symposium.city.statusAwake'))
  else if (cityState.value === 'asleep') setStatus('ready', t('step5.symposium.city.statusAsleep'))
  else setStatus('ready')
}

// Seats
const saveChatHistory = () => {
  if (chatTarget.value === 'report_agent') {
    chatHistoryCache.value.report_agent = [...chatHistory.value]
  } else if (selectedAgentIndex.value !== null) {
    chatHistoryCache.value[`agent_${selectedAgentIndex.value}`] = [...chatHistory.value]
  }
}

const sitWithScribe = () => {
  saveChatHistory()
  mode.value = 'chat'
  chatTarget.value = 'report_agent'
  selectedAgent.value = null
  selectedAgentIndex.value = null
  chatHistory.value = chatHistoryCache.value.report_agent || []
  addLog(t('step5.symposium.ledger.sat', { name: t('step5.symposium.scribe') }))
  goToTable()
}

const sitWith = (citizen, idx) => {
  saveChatHistory()
  mode.value = 'chat'
  selectedAgent.value = profiles.value[idx]
  selectedAgentIndex.value = idx
  chatTarget.value = 'agent'
  chatHistory.value = chatHistoryCache.value[`agent_${idx}`] || []
  addLog(t('step5.symposium.ledger.sat', { name: citizen.name }))
  if (!cityAwake.value) checkCity()
  goToTable()
}

const focusInput = () => {
  nextTick(() => {
    const el = chatInputRef.value
    if (el && !el.disabled) el.focus({ preventScroll: true })
  })
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

// The table stands below the room; sitting down carries the visitor to it
// (unless it is already in view), so the dialogue is where they look.
const revealTable = () => {
  nextTick(() => {
    const el = tableRef.value
    if (!el || typeof el.scrollIntoView !== 'function' || typeof window === 'undefined') return
    const top = el.getBoundingClientRect().top
    const header = rootRef.value ? parseFloat(getComputedStyle(rootRef.value).getPropertyValue('--p-header-h')) || 64 : 64
    if (top >= header && top < window.innerHeight * 0.5) return
    el.scrollIntoView({ block: 'start', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  })
}

// After sitting down: on wide screens the caret waits in the question; on
// phones focus lands on the seated name, so the keyboard does not rise over the face.
const goToTable = () => {
  revealTable()
  if (!isNarrow.value) {
    focusInput()
    return
  }
  nextTick(() => {
    // The band that is arriving, not the one leaving.
    const name = tableRef.value ? tableRef.value.querySelector('.table-band:not(.seat-leave-active) .band-name') : null
    if (name) name.focus({ preventScroll: true })
  })
}

const toggleCrowdMode = () => {
  if (mode.value === 'crowd') {
    mode.value = 'chat'
    goToTable()
  } else {
    saveChatHistory()
    mode.value = 'crowd'
    if (!cityAwake.value) checkCity()
  }
}

const growInput = () => {
  const el = chatInputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 200)}px`
}

// What the Scribe and the citizens write comes as Markdown.
const renderMarkdown = (content) => {
  if (!content) return ''

  let processedContent = content.replace(/^##\s+.+\n+/, '')
  let html = processedContent.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="code-block"><code>$2</code></pre>')
  html = html.replace(/`([^`]+)`/g, '<code class="inline-code">$1</code>')
  html = html.replace(/^#### (.+)$/gm, '<h5 class="md-h5">$1</h5>')
  html = html.replace(/^### (.+)$/gm, '<h4 class="md-h4">$1</h4>')
  html = html.replace(/^## (.+)$/gm, '<h3 class="md-h3">$1</h3>')
  html = html.replace(/^# (.+)$/gm, '<h2 class="md-h2">$1</h2>')
  html = html.replace(/^> (.+)$/gm, '<blockquote class="md-quote">$1</blockquote>')

  html = html.replace(/^(\s*)- (.+)$/gm, (match, indent, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-li" data-level="${level}">${text}</li>`
  })
  html = html.replace(/^(\s*)(\d+)\. (.+)$/gm, (match, indent, num, text) => {
    const level = Math.floor(indent.length / 2)
    return `<li class="md-oli" data-level="${level}">${text}</li>`
  })

  html = html.replace(/(<li class="md-li"[^>]*>.*?<\/li>\s*)+/g, '<ul class="md-ul">$&</ul>')
  html = html.replace(/(<li class="md-oli"[^>]*>.*?<\/li>\s*)+/g, '<ol class="md-ol">$&</ol>')

  html = html.replace(/<\/li>\s+<li/g, '</li><li')
  html = html.replace(/<ul class="md-ul">\s+/g, '<ul class="md-ul">')
  html = html.replace(/<ol class="md-ol">\s+/g, '<ol class="md-ol">')
  html = html.replace(/\s+<\/ul>/g, '</ul>')
  html = html.replace(/\s+<\/ol>/g, '</ol>')

  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>')
  html = html.replace(/_(.+?)_/g, '<em>$1</em>')
  html = html.replace(/^---$/gm, '<hr class="md-hr">')
  html = html.replace(/\n\n/g, '</p><p class="md-p">')
  html = html.replace(/\n/g, '<br>')
  html = '<p class="md-p">' + html + '</p>'
  html = html.replace(/<p class="md-p"><\/p>/g, '')
  html = html.replace(/<p class="md-p">(<h[2-5])/g, '$1')
  html = html.replace(/(<\/h[2-5]>)<\/p>/g, '$1')
  html = html.replace(/<p class="md-p">(<ul|<ol|<blockquote|<pre|<hr)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>|<\/pre>)<\/p>/g, '$1')
  html = html.replace(/<br>\s*(<ul|<ol|<blockquote)/g, '$1')
  html = html.replace(/(<\/ul>|<\/ol>|<\/blockquote>)\s*<br>/g, '$1')
  html = html.replace(/<p class="md-p">(<br>\s*)+(<ul|<ol|<blockquote|<pre|<hr)/g, '$2')
  html = html.replace(/(<br>\s*){2,}/g, '<br>')
  html = html.replace(/(<\/ol>|<\/ul>|<\/blockquote>)<br>(<p|<div)/g, '$1$2')

  // Ordered lists split by prose keep counting.
  const tokens = html.split(/(<ol class="md-ol">(?:<li class="md-oli"[^>]*>[\s\S]*?<\/li>)+<\/ol>)/g)
  let olCounter = 0
  let inSequence = false
  for (let i = 0; i < tokens.length; i++) {
    if (tokens[i].startsWith('<ol class="md-ol">')) {
      const liCount = (tokens[i].match(/<li class="md-oli"/g) || []).length
      if (liCount === 1) {
        olCounter++
        if (olCounter > 1) {
          tokens[i] = tokens[i].replace('<ol class="md-ol">', `<ol class="md-ol" start="${olCounter}">`)
        }
        inSequence = true
      } else {
        olCounter = 0
        inSequence = false
      }
    } else if (inSequence) {
      if (/<h[2-5]/.test(tokens[i])) {
        olCounter = 0
        inSequence = false
      }
    }
  }
  html = tokens.join('')

  return html
}

// Markdown to plain words, for reading aloud and for the Scribe's reading of the crowd.
const plainWords = (content) =>
  String(content || '')
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/[#>*_`]+/g, '')
    .replace(/\[(.*?)\]\(.*?\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()

// Answers can be heard in the city's own voices: nothing sounds until a hear
// button is pressed, and only one voice speaks at a time. A long answer comes
// in parts; the next part is asked for while the one before plays. When the
// voices are resting (or fail), the browser's own voice reads instead.
const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window && typeof window.SpeechSynthesisUtterance !== 'undefined'
const canPlay = typeof window !== 'undefined' && typeof window.HTMLAudioElement !== 'undefined'
const canHear = canSpeak || canPlay
const speakingKey = ref(null)
const hearPhase = ref('idle') // idle | gathering | speaking
const hearNote = ref({ key: null, text: '' })
const hearAnnouncement = ref('')
const voiceRef = ref(null)
let spareAudio = null
let hearToken = 0
// After a 503 the voices are left to rest a minute before they are asked again.
const RESTING_MS = 60000
let restingUntil = 0
// A breath of silence, played inside the click so the phone lets the voice sound when it arrives.
const SILENCE = 'data:audio/wav;base64,UklGRjQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YRAAAACAgICAgICAgICAgICAgICA'

const voiceElement = () => {
  if (voiceRef.value) return voiceRef.value
  if (!spareAudio && canPlay) spareAudio = new window.Audio()
  return spareAudio
}
const quietAudio = () => {
  const el = voiceElement()
  if (!el) return
  el.onended = null
  el.onerror = null
  el.onplaying = null
  try {
    el.pause()
    el.removeAttribute('src')
    el.load()
  } catch { /* nothing was playing */ }
}

// Who is speaking, as the voice route wants to know them.
const chatSpeaker = () =>
  companion.value
    ? { voice: voiceForType(companion.value.type), agentId: companion.value.agentId, name: companion.value.name }
    : { voice: 'scribe' }
const crowdSpeaker = (r) => ({ voice: voiceForType(r.type), agentId: r.agentId, name: r.name })

// When a Stop button (or the hear button) leaves with the voice, focus goes to the answer's hear button.
const keepFocus = (key) => {
  if (typeof document === 'undefined') return
  const active = document.activeElement
  const holder = active && active.closest ? active.closest('[data-voicing]') : null
  if (!holder || holder.getAttribute('data-voicing') !== key) return
  nextTick(() => {
    const btn = rootRef.value?.querySelector(`.hear[data-hear="${key}"]`)
    if (btn) btn.focus()
  })
}

const stopHearing = (announce = true) => {
  const was = speakingKey.value
  hearToken++
  quietAudio()
  if (canSpeak) {
    try { window.speechSynthesis.cancel() } catch { /* nothing to stop */ }
  }
  if (was) keepFocus(was)
  speakingKey.value = null
  hearPhase.value = 'idle'
  if (was && announce) hearAnnouncement.value = t('step5.symposium.hearing.stopped')
}
const stopFrom = (key) => {
  if (speakingKey.value === key) stopHearing()
}
const finishHearing = (token) => {
  if (token !== hearToken) return
  const was = speakingKey.value
  quietAudio()
  if (was) keepFocus(was)
  speakingKey.value = null
  hearPhase.value = 'idle'
  hearAnnouncement.value = t('step5.symposium.hearing.stopped')
}
const nowSpeaking = (token) => {
  if (token !== hearToken || hearPhase.value === 'speaking') return
  hearPhase.value = 'speaking'
  hearAnnouncement.value = t('step5.symposium.hearing.speaking')
}

// The browser's own voice, as before the city had voices of its own.
const readInBrowser = (key, words, token) => {
  if (!canSpeak) {
    hearNote.value = { key, text: t('step5.symposium.hearing.restingQuiet') }
    finishHearing(token)
    return
  }
  hearNote.value = { key, text: t('step5.symposium.hearing.resting') }
  try {
    const u = new window.SpeechSynthesisUtterance(words)
    const zh = String(locale.value || '').startsWith('zh')
    u.lang = zh ? 'zh-CN' : 'en-GB'
    u.rate = 0.96
    const voice = window.speechSynthesis.getVoices().find((v) => v.lang && v.lang.toLowerCase().startsWith(zh ? 'zh' : 'en-gb'))
    if (voice) u.voice = voice
    u.onstart = () => nowSpeaking(token)
    u.onend = () => finishHearing(token)
    u.onerror = u.onend
    window.speechSynthesis.speak(u)
    nowSpeaking(token)
  } catch {
    finishHearing(token)
  }
}

// One recorded part, from the first sound to the last.
const playPart = (url, token) =>
  new Promise((resolve, reject) => {
    const el = voiceElement()
    if (!el || !url) {
      reject(new Error('no voice'))
      return
    }
    el.onended = () => resolve()
    el.onerror = () => reject(new Error('the recording would not play'))
    el.onplaying = () => nowSpeaking(token)
    el.src = url
    try {
      const played = el.play()
      if (played && typeof played.catch === 'function') played.catch(reject)
    } catch (err) {
      reject(err)
    }
  })

const askPart = (body, part) =>
  speakWords({ ...body, part }).then((res) => {
    const data = res && res.data
    if (!data || !data.url) throw new Error('no voice')
    return data
  })

// The city's voice: part 0 as soon as it comes, the next asked for while it plays.
const speakInCity = async (key, words, body, token) => {
  let spoke = false
  let part = 0
  let parts = 1
  let coming = askPart(body, 0)
  while (part < parts) {
    try {
      const data = await coming
      if (token !== hearToken) return
      parts = Math.max(1, Number(data.parts) || 1)
      coming = part + 1 < parts ? askPart(body, part + 1) : null
      // Asked for now, heard later; a failure is met when its turn comes.
      if (coming) coming.catch(() => {})
      await playPart(filmAssetUrl(data.url), token)
      if (token !== hearToken) return
      spoke = true
      part += 1
    } catch (err) {
      if (token !== hearToken) return
      if (err && err.response && err.response.status === 503) restingUntil = Date.now() + RESTING_MS
      if (!spoke) {
        quietAudio()
        readInBrowser(key, words, token)
      } else {
        hearNote.value = { key, text: t('step5.symposium.hearing.brokeOff') }
        finishHearing(token)
      }
      return
    }
  }
  finishHearing(token)
}

const hear = (key, content, speaker = { voice: 'scribe' }) => {
  if (!canHear) return
  if (speakingKey.value === key) {
    stopHearing()
    return
  }
  stopHearing(false)
  hearNote.value = { key: null, text: '' }
  const words = plainWords(content)
  if (!words) return
  const token = ++hearToken
  speakingKey.value = key
  hearPhase.value = 'gathering'
  if (!canPlay || Date.now() < restingUntil) {
    readInBrowser(key, words, token)
    return
  }
  // Played inside the click itself: a phone then lets the voice sound when it arrives.
  const el = voiceElement()
  if (el) {
    try {
      el.src = SILENCE
      const warmed = el.play()
      if (warmed && typeof warmed.catch === 'function') warmed.catch(() => {})
    } catch { /* the voice will ask again */ }
  }
  const body = { text: words, voice: speaker.voice || 'scribe', lang: String(locale.value || 'en'), part: 0 }
  if (props.simulationId) body.simulation_id = props.simulationId
  if (speaker.agentId !== undefined && speaker.agentId !== null) body.agent_id = speaker.agentId
  if (speaker.name) body.name = speaker.name
  speakInCity(key, words, body, token)
}

// The Socratic chips insert a question at the end of what is written; they never send.
const insertSocraticPrompt = (q) => {
  if (isChatInputDisabled.value) return
  const current = chatInput.value.replace(/\s+$/, '')
  chatInput.value = current ? `${current}\n${q}` : q
  nextTick(() => {
    const el = chatInputRef.value
    if (!el) return
    growInput()
    el.focus()
    const end = el.value.length
    el.setSelectionRange(end, end)
    el.scrollTop = el.scrollHeight
  })
}

// Asking
const sendMessage = async () => {
  if (!chatInput.value.trim() || isChatInputDisabled.value) return

  const message = chatInput.value.trim()
  chatInput.value = ''
  nextTick(growInput)

  chatHistory.value.push({ role: 'user', content: message, timestamp: new Date().toISOString() })
  isSending.value = true
  setStatus('working', workingText.value)
  scrollToEnd()

  try {
    if (chatTarget.value === 'report_agent') {
      await sendToScribe(message)
    } else {
      await sendToCitizen(message)
    }
    isSending.value = false
    setIdle()
  } catch (err) {
    addLog(t('step5.symposium.ledger.failed', { error: err.message }))
    chatHistory.value.push({
      role: 'assistant',
      content: t('step5.symposium.trouble', { error: err.message }),
      timestamp: new Date().toISOString()
    })
    setStatus('error')
  } finally {
    isSending.value = false
    saveChatHistory()
    scrollToEnd()
    focusInput()
  }
}

const sendToScribe = async (message) => {
  addLog(t('step5.symposium.ledger.asked', { name: t('step5.symposium.scribe'), q: message.substring(0, 60) }))

  const historyForApi = chatHistory.value
    .slice(0, -1)
    .slice(-10)
    .map((msg) => ({ role: msg.role, content: msg.content }))

  const res = await chatWithReport({
    simulation_id: props.simulationId,
    message,
    chat_history: historyForApi
  })

  if (res.success && res.data) {
    chatHistory.value.push({
      role: 'assistant',
      content: res.data.response || res.data.answer || t('step5.noResponse'),
      timestamp: new Date().toISOString()
    })
    addLog(t('step5.symposium.ledger.answered', { name: t('step5.symposium.scribe') }))
  } else {
    throw new Error(res.error || t('step5.requestFailed'))
  }
}

const sendToCitizen = async (message) => {
  if (!selectedAgent.value || selectedAgentIndex.value === null || !companion.value) {
    throw new Error(t('step5.symposium.needSeat'))
  }
  const name = companion.value.name
  addLog(t('step5.symposium.ledger.asked', { name, q: message.substring(0, 60) }))

  // The citizen is reminded of the conversation so far.
  let prompt = message
  if (chatHistory.value.length > 1) {
    const historyContext = chatHistory.value
      .slice(0, -1)
      .slice(-6)
      .map((msg) => `${msg.role === 'user' ? 'Questioner' : 'You'}: ${msg.content}`)
      .join('\n')
    prompt = `Earlier in our conversation:\n${historyContext}\n\nNow my next question is: ${message}`
  }

  const res = await interviewAgents({
    simulation_id: props.simulationId,
    interviews: [{ agent_id: selectedAgentIndex.value, prompt }]
  })

  if (res.success && res.data) {
    // Results come keyed by square and seat: { reddit_0: {...}, twitter_0: {...} }
    const resultData = res.data.result || res.data
    const resultsDict = resultData.results || resultData
    let responseContent = null
    const agentId = selectedAgentIndex.value

    if (typeof resultsDict === 'object' && !Array.isArray(resultsDict)) {
      const agentResult = resultsDict[`reddit_${agentId}`] || resultsDict[`twitter_${agentId}`] || Object.values(resultsDict)[0]
      if (agentResult) responseContent = agentResult.response || agentResult.answer
    } else if (Array.isArray(resultsDict) && resultsDict.length > 0) {
      responseContent = resultsDict[0].response || resultsDict[0].answer
    }

    if (responseContent) {
      chatHistory.value.push({ role: 'assistant', content: responseContent, timestamp: new Date().toISOString() })
      addLog(t('step5.symposium.ledger.answered', { name }))
    } else {
      throw new Error(t('step5.noResponse'))
    }
  } else {
    throw new Error(res.error || t('step5.requestFailed'))
  }
}

const scrollToEnd = () => {
  nextTick(() => {
    const lines = document.querySelectorAll('.symposium .dialogue > .line')
    const last = lines[lines.length - 1]
    if (last && typeof last.scrollIntoView === 'function') last.scrollIntoView({ block: 'nearest' })
  })
}

// The crowd
const toggleAgentSelection = (idx) => {
  const next = new Set(selectedAgents.value)
  if (next.has(idx)) next.delete(idx)
  else next.add(idx)
  selectedAgents.value = next
}

const selectAllAgents = () => {
  selectedAgents.value = new Set(profiles.value.map((_, idx) => idx))
}

const clearAgentSelection = () => {
  selectedAgents.value = new Set()
}

// How an answer leans, when the question can be answered yes or no.
const YES_NO_QUESTION = /^(?:(?:and|but|so|then|now|tell me|honestly),?\s+)?(do|does|did|would|will|should|shall|is|are|was|were|can|could|have|has|had|may|might|must|won't|wouldn't|isn't|aren't|don't|doesn't)\b/i
const isYesNoQuestion = (q) => {
  const text = String(q || '').trim()
  return YES_NO_QUESTION.test(text) || /[吗嘛][？?]?$/.test(text)
}
const LEAN_NO = /^(no\b|nay\b|never\b|not\b|absolutely not|certainly not|of course not|i would not|i wouldn't|i will not|i won't|i do not|i don't|i did not|i didn't|i am not|i'm not|i cannot|i can't|i could not|i couldn't|i refuse|we would not|we wouldn't|we will not|we won't|we do not|we don't|we cannot|we can't|we refuse|不|绝不|我不)/i
const LEAN_YES = /^(yes\b|yea\b|aye\b|absolutely\b|certainly\b|of course\b|indeed\b|gladly\b|definitely\b|i would\b|i will\b|i do\b|i did\b|i am\b|i'd\b|i'll\b|we would\b|we will\b|we do\b|we'd\b|we'll\b|是|会|愿意|当然)/i
const leanOf = (answer) => {
  const opening = plainWords(answer).replace(/^["“'‘(\s]+/, '').slice(0, 80)
  if (LEAN_NO.test(opening)) return 'no'
  if (LEAN_YES.test(opening)) return 'yes'
  return 'unsure'
}

const submitSurvey = async () => {
  if (!canAskCrowd.value) return

  isSurveying.value = true
  setStatus('working', t('step5.symposium.crowdAnswering'))
  addLog(t('step5.symposium.ledger.crowdAsked', { n: selectedAgents.value.size }))

  try {
    const questionText = surveyQuestion.value.trim()
    const interviews = Array.from(selectedAgents.value).map((idx) => ({ agent_id: idx, prompt: questionText }))

    const res = await interviewAgents({
      simulation_id: props.simulationId,
      interviews
    })

    if (res.success && res.data) {
      const resultData = res.data.result || res.data
      const resultsDict = resultData.results || resultData
      const list = []

      for (const interview of interviews) {
        const agentIdx = interview.agent_id
        const citizen = citizens.value[agentIdx]
        let responseContent = ''

        if (typeof resultsDict === 'object' && !Array.isArray(resultsDict)) {
          const agentResult = resultsDict[`reddit_${agentIdx}`] || resultsDict[`twitter_${agentIdx}`]
          if (agentResult) responseContent = agentResult.response || agentResult.answer || ''
        } else if (Array.isArray(resultsDict)) {
          const matched = resultsDict.find((r) => r.agent_id === agentIdx)
          if (matched) responseContent = matched.response || matched.answer || ''
        }

        const spoke = !!String(responseContent).trim()
        list.push({
          agent_id: agentIdx,
          agentId: citizen ? citizen.agentId : agentIdx,
          name: citizen ? citizen.name : `Citizen ${agentIdx + 1}`,
          type: citizen ? citizen.type : '',
          color: citizen ? citizen.color : ROLE_COLOR_VAR.people,
          ring: citizen ? citizen.ring : ROLE_COLOR_VAR.people,
          role: citizen ? citizen.role : '',
          stance: citizen ? citizen.stance : null,
          question: questionText,
          answer: spoke ? responseContent : t('step5.symposium.noAnswer'),
          spoke,
          lean: spoke ? leanOf(responseContent) : 'silent'
        })
      }

      surveyResults.value = list
      quorumActive.value = (list.find((r) => r.spoke) || list[0] || {}).agent_id ?? null
      allAnswersOpen.value = false
      addLog(t('step5.symposium.ledger.crowdAnswered', { n: list.filter((r) => r.spoke).length }))
      isSurveying.value = false
      setIdle()
      readTheCrowd(questionText, list)
    } else {
      throw new Error(res.error || t('step5.requestFailed'))
    }
  } catch (err) {
    addLog(t('step5.symposium.ledger.failed', { error: err.message }))
    setStatus('error')
  } finally {
    isSurveying.value = false
  }
}

// The quorum: the faces grouped by how they answered (a yes or no question) or
// by where they stood, with one line above them.
const quorumMode = computed(() => {
  const list = surveyResults.value
  const spoke = list.filter((r) => r.spoke)
  if (!spoke.length) return 'count'
  if (isYesNoQuestion(list[0]?.question)) {
    const decided = spoke.filter((r) => r.lean === 'yes' || r.lean === 'no').length
    if (decided * 2 >= spoke.length) return 'lean'
  }
  if (spoke.some((r) => r.stance)) return 'stance'
  return 'count'
})
const GROUP_ORDER = {
  lean: ['yes', 'unsure', 'no'],
  stance: ['for', 'between', 'aside', 'against', 'all'],
  count: ['all']
}
const groupKeyOf = (r, how) => {
  if (!r.spoke) return 'silent'
  if (how === 'lean') return r.lean
  if (how === 'stance') return r.stance ? r.stance.key : 'all'
  return 'all'
}
const quorumGroups = computed(() => {
  const how = quorumMode.value
  const buckets = {}
  for (const r of surveyResults.value) (buckets[groupKeyOf(r, how)] ||= []).push(r)
  return [...GROUP_ORDER[how], 'silent']
    .filter((key) => buckets[key] && buckets[key].length)
    .map((key) => ({ key, label: t(`step5.symposium.quorum.groups.${key}`), items: buckets[key] }))
})
const quorumOrder = computed(() => quorumGroups.value.flatMap((g) => g.items))
const activeAnswer = computed(() => quorumOrder.value.find((r) => r.agent_id === quorumActive.value) || quorumOrder.value[0] || null)
const quorumTallyWords = computed(() => quorumGroups.value.map((g) => `${g.label} ${g.items.length}`).join(', '))

const countPhrase = computed(() => {
  const n = surveyResults.value.filter((r) => r.spoke).length
  return n === 1 ? t('step5.symposium.quorum.countOne') : t('step5.symposium.quorum.count', { n, w: inWords(n) })
})
const localParts = computed(() => {
  if (quorumMode.value === 'count') return []
  const groups = quorumGroups.value.filter((g) => g.key !== 'silent' && g.key !== 'all')
  const silent = quorumGroups.value.find((g) => g.key === 'silent')
  const part = (key, n) => t(`step5.symposium.quorum.${key}`, { n, w: inWords(n) })
  const parts = groups.map((g) => part(g.key, g.items.length))
  if (silent) parts.push(part('silent', silent.items.length))
  return parts
})
const localLine = computed(() => {
  const how = quorumMode.value
  const count = countPhrase.value
  const parts = localParts.value
  if (how === 'lean' && parts.length) return capital(t('step5.symposium.quorum.leanLine', { count, parts: joinList(parts) }))
  if (how === 'stance' && parts.length) return capital(t('step5.symposium.quorum.stanceLine', { count, parts: joinList(parts) }))
  return capital(t('step5.symposium.quorum.countLine', { count }))
})
const COMMON_OPENERS = /^(most|many|nearly|almost|all|half|few|a few|some|none|no one|nobody|the|they|each|every|only|several|a|an|more|less|fewer|two|three|four|five|six|seven|eight|nine|ten)\b/i
const quorumHeadline = computed(() => {
  if (readingState.value === 'done' && quorumReading.value) {
    const r = quorumReading.value
    const reading = COMMON_OPENERS.test(r) ? r.charAt(0).toLowerCase() + r.slice(1) : r
    return capital(t('step5.symposium.quorum.withReading', { count: countPhrase.value, reading }))
  }
  return localLine.value
})
const quorumSubline = computed(() => {
  if (readingState.value === 'reading') return t('step5.symposium.quorum.readingPending')
  // Under the Scribe's reading, the count as it fell, without saying the number twice.
  if (readingState.value === 'done') return localParts.value.length ? capital(t('step5.symposium.quorum.partsLine', { parts: joinList(localParts.value) })) : ''
  return ''
})
const portraitOf = (r) => portraitFor(r.agentId) || portraitFor(r.name) || ''

// For listeners: once when the answers are in, and again when the Scribe has read them.
const quorumAnnouncement = computed(() => {
  if (isSurveying.value || !surveyResults.value.length) return ''
  if (readingState.value === 'done') return quorumHeadline.value
  return t('step5.symposium.crowdAnsweredLive', { line: localLine.value })
})

// A tap (or Enter) on a face: on a phone the answer opens below the faces, so
// the page brings it up to where the finger is.
const pickFace = (agentId) => {
  quorumActive.value = agentId
  if (!isNarrow.value) return
  nextTick(() => {
    const el = typeof document !== 'undefined' ? document.getElementById('quorum-voice') : null
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest', behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
    }
  })
}

// Arrow keys walk the faces; Home and End go to the first and last.
const onQuorumKey = (e, agentId) => {
  const order = quorumOrder.value
  const i = order.findIndex((r) => r.agent_id === agentId)
  if (i < 0) return
  let next = -1
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = Math.min(order.length - 1, i + 1)
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = Math.max(0, i - 1)
  else if (e.key === 'Home') next = 0
  else if (e.key === 'End') next = order.length - 1
  if (next < 0) return
  e.preventDefault()
  quorumActive.value = order[next].agent_id
  nextTick(() => {
    const el = rootRef.value?.querySelector(`.q-face[data-agent="${order[next].agent_id}"]`)
    if (el) el.focus()
  })
}

// The Scribe reads the answers and says, in one line, where the crowd came down.
let readingToken = 0
const oneSentence = (text) => {
  let s = plainWords(text)
    .replace(/[“”"]/g, '')
    .replace(/\s*[\u2014\u2013]\s*/g, ', ')
    .trim()
  const first = s.match(/^.+?[.!?。！？](?=\s|$)/)
  if (first) s = first[0]
  s = s.replace(/[.!?。！？\s]+$/, '')
  return s.length > 200 ? `${s.slice(0, 190).replace(/\s+\S*$/, '')}…` : s
}
const readTheCrowd = async (questionText, list) => {
  const token = ++readingToken
  quorumReading.value = ''
  const spoke = list.filter((r) => r.spoke)
  if (spoke.length < 2) {
    readingState.value = 'idle'
    return
  }
  readingState.value = 'reading'
  const answers = spoke
    .slice(0, 24)
    .map((r) => `- ${r.name}: ${plainWords(r.answer).slice(0, 420)}`)
    .join('\n')
  const message = [
    `I put one question to ${spoke.length} citizens: "${questionText}"`,
    '',
    'Their answers:',
    answers,
    '',
    'In one sentence of no more than eighteen words, tell me where most of them came down. Begin with a word such as "most", "many", "nearly all", "half" or "few". Answer from these answers alone; no lists, no names, no quotation marks.'
  ].join('\n')
  try {
    const res = await chatWithReport({ simulation_id: props.simulationId, message, chat_history: [] })
    if (token !== readingToken) return
    const text = res && res.success && res.data ? oneSentence(res.data.response || res.data.answer || '') : ''
    if (text) {
      quorumReading.value = text
      readingState.value = 'done'
      addLog(t('step5.symposium.ledger.read'))
    } else {
      readingState.value = 'failed'
    }
  } catch {
    if (token === readingToken) readingState.value = 'failed'
  }
}

// The Chronicle
const loadReportData = async () => {
  if (!props.reportId) return
  try {
    const reportRes = await getReport(props.reportId)
    if (reportRes.success && reportRes.data) {
      const record = reportRes.data
      question.value = record.simulation_requirement || ''
      await loadAgentLogs()
      // The finished record carries the chapters too, should the Scribe's notes be missing.
      if (!reportOutline.value && record.outline) {
        reportOutline.value = record.outline
        ;(record.outline.sections || []).forEach((s, i) => {
          if (s.content && !generatedSections.value[i + 1]) generatedSections.value[i + 1] = s.content
        })
      }
      // The summary is what she saw; keep it even if her notes carried an outline without one.
      if (reportOutline.value && !reportOutline.value.summary && record.outline?.summary) {
        reportOutline.value = { ...reportOutline.value, summary: record.outline.summary }
      }
      if (reportOutline.value) addLog(t('step5.symposium.ledger.chronicle'))
    } else {
      addLog(t('step5.symposium.ledger.chronicleMissing', { error: reportRes.error || t('common.unknownError') }))
    }
  } catch (err) {
    addLog(t('step5.symposium.ledger.chronicleMissing', { error: err.message }))
  }
}

const loadAgentLogs = async () => {
  if (!props.reportId) return
  try {
    const res = await getAgentLog(props.reportId, 0)
    if (res.success && res.data) {
      const logs = res.data.logs || []
      logs.forEach((log) => {
        if (log.action === 'planning_complete' && log.details?.outline) {
          reportOutline.value = log.details.outline
        }
        if (log.action === 'section_complete' && log.section_index < 100 && log.details?.content) {
          generatedSections.value[log.section_index] = log.details.content
        }
      })
    }
  } catch (err) {
    addLog(t('step5.symposium.ledger.chronicleMissing', { error: err.message }))
  }
}

const loadProfiles = async () => {
  if (!props.simulationId) return
  try {
    const res = await getSimulationProfilesRealtime(props.simulationId)
    if (res.success && res.data) {
      profiles.value = res.data.profiles || []
      addLog(t('step5.symposium.ledger.profiles', { n: profiles.value.length }))
    }
  } catch (err) {
    addLog(t('step5.symposium.ledger.profilesMissing', { error: err.message }))
  }
}

// Where each citizen stood when the argument began.
const loadConfig = async () => {
  const sim = props.simulationId
  if (!sim) return
  try {
    const res = await getSimulationConfig(sim)
    if (sim !== props.simulationId) return
    const list = res && res.success && res.data ? res.data.agent_configs : null
    agentConfigs.value = Array.isArray(list) ? list : []
  } catch {
    // Without it the wall shows faces and words, and no stance.
  }
}

// Their own words, from both squares.
const loadVoices = async () => {
  const sim = props.simulationId
  if (!sim) return
  const [agora, stoa] = await Promise.allSettled([
    getSimulationPosts(sim, 'twitter', 400, 0),
    getSimulationPosts(sim, 'reddit', 400, 0)
  ])
  if (sim !== props.simulationId) return
  const byAgent = {}
  const gather = (settled, place) => {
    if (settled.status !== 'fulfilled' || !settled.value || !settled.value.success) return
    for (const post of settled.value.data?.posts || []) {
      const id = Number(post.user_id)
      const words = ownWords(post)
      if (!Number.isFinite(id) || !String(words).trim()) continue
      ;(byAgent[id] ||= []).push({ ...post, words, place })
    }
  }
  gather(agora, 'agora')
  gather(stoa, 'stoa')
  const out = {}
  for (const [id, posts] of Object.entries(byAgent)) {
    const voice = voiceOf(posts)
    if (voice) out[id] = voice
  }
  voices.value = out
  if (Object.keys(out).length) addLog(t('step5.symposium.ledger.voices'))
}

// Whether the citizens can be questioned tonight: only while the city is awake.
let lastCityCheck = 0
let cityTimer = 0
const checkCity = async () => {
  if (!props.simulationId) return
  const now = Date.now()
  if (now - lastCityCheck < 15000) return
  lastCityCheck = now
  try {
    const res = await getEnvStatus({ simulation_id: props.simulationId })
    const next = res.success && res.data && res.data.env_alive ? 'awake' : 'asleep'
    if (next !== cityState.value) {
      addLog(t(next === 'awake' ? 'step5.symposium.ledger.awake' : 'step5.symposium.ledger.asleep'))
    }
    cityState.value = next
    if (!isSending.value && !isSurveying.value) setIdle()
  } catch {
    // Leave the room as it was; the ask itself will say if it fails.
  }
}
const CITY_POLL_MS = 30000
const watchCity = () => {
  clearInterval(cityTimer)
  cityTimer = setInterval(() => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    checkCity()
  }, CITY_POLL_MS)
}

// The drawer
let previousOverflow = ''
const openChronicle = () => {
  chronicleOpen.value = true
  try {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  } catch { /* nothing to lock */ }
  nextTick(() => chronicleClose.value?.focus())
}

// Tab cycles inside the open Chronicle; the room behind it waits.
const trapFocus = (e) => {
  const root = e.currentTarget
  if (!root) return
  const focusable = Array.from(root.querySelectorAll('button, [href], textarea, input, select, [tabindex]:not([tabindex="-1"])')).filter((el) => !el.disabled)
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

const closeChronicle = () => {
  chronicleOpen.value = false
  try { document.body.style.overflow = previousOverflow } catch { /* nothing to restore */ }
  nextTick(() => chronicleToggle.value?.focus())
}

// Lifecycle
onMounted(() => {
  if (narrowQuery) {
    if (narrowQuery.addEventListener) narrowQuery.addEventListener('change', onNarrowChange)
    else if (narrowQuery.addListener) narrowQuery.addListener(onNarrowChange)
  }
  loadReportData()
  loadProfiles()
  loadConfig()
  loadVoices()
  checkCity()
  watchCity()
})

onBeforeUnmount(() => {
  if (narrowQuery) {
    if (narrowQuery.removeEventListener) narrowQuery.removeEventListener('change', onNarrowChange)
    else if (narrowQuery.removeListener) narrowQuery.removeListener(onNarrowChange)
  }
  clearInterval(cityTimer)
  readingToken++
  stopHearing()
  if (chronicleOpen.value) {
    try { document.body.style.overflow = previousOverflow } catch { /* nothing to restore */ }
  }
})

watch(() => props.reportId, (newId, oldId) => {
  if (newId && newId !== oldId) loadReportData()
})

watch(() => props.simulationId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    lastCityCheck = 0
    agentConfigs.value = []
    voices.value = {}
    loadProfiles()
    loadConfig()
    loadVoices()
    checkCity()
  }
})

// A seat change or a new crowd stops any voice still reading; so does another face in the quorum.
const hushAll = () => {
  stopHearing()
  hearNote.value = { key: null, text: '' }
}
watch([selectedAgentIndex, chatTarget, mode], hushAll)
watch(surveyResults, hushAll)
watch(() => (activeAnswer.value ? activeAnswer.value.agent_id : null), (id) => {
  const key = speakingKey.value || hearNote.value.key
  if (key && key.startsWith('q-') && key !== `q-${id}`) hushAll()
})
</script>

<style scoped>
/* The act: the room's caption, the painted room across the page, then who is
   here tonight beside the two doors, and the table at reading measure. The
   order on the screen is the order of the page, for eyes and for keys alike. */
.symposium {
  width: 100%;
  max-width: 1360px;
  margin: 0 auto;
  padding: 28px var(--p-gutter) 48px;
  box-sizing: border-box;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas:
    'head    state'
    'stage   stage'
    'actions actions'
    'table   table';
  column-gap: 32px;
  font-family: var(--p-font-body);
  color: var(--p-ink-2);
  min-width: 0;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* Buttons that must stay a finger wide on every screen. */
.p-button.tall {
  min-height: 40px;
  padding-block: 0;
  font-size: var(--t-sm);
}

/* The room's caption */
.room-head { grid-area: head; min-width: 0; }

.room-title {
  margin: 6px 0 4px;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 500;
  line-height: 1;
  color: var(--p-ink);
}

/* Beside the caption on wide screens: who is here, and whether the city is awake. */
.room-state {
  grid-area: state;
  align-self: end;
  justify-self: end;
  max-width: 34em;
  min-width: 0;
  text-align: right;
}

/* Right-aligned beside the room's name: the lamp rides inline with the first
   word, so it stays beside the sentence however the line wraps. */
.room-state .city-state { display: block; text-align: right; margin-left: auto; }
.room-state .city-lamp { display: inline-block; margin-right: 8px; vertical-align: 1px; transform: none; }
.room-state .painters { margin-left: 0; }

.room-line {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-3);
}

/* Whether the city is awake: a lamp and one sentence. */
.city-state {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin: 10px 0 0;
  font-size: var(--t-sm);
  line-height: 1.45;
  color: var(--p-ink-2);
  max-width: 44em;
}

.city-lamp {
  flex: 0 0 auto;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 1px solid var(--p-ink-4);
  transform: translateY(-1px);
}

.city-state.is-awake .city-lamp {
  background: var(--p-olive);
  border-color: var(--p-olive);
  box-shadow: 0 0 0 4px var(--p-olive-tint), 0 0 14px rgba(168, 184, 106, 0.55);
  animation: lamp 2.4s ease-in-out infinite;
}

.city-state.is-asleep .city-lamp { background: transparent; border-color: var(--p-ink-3); }
.city-state.is-asleep { color: var(--p-ink-3); }
.city-state.is-unknown { color: var(--p-ink-4); font-style: italic; }

@keyframes lamp {
  0%, 100% { box-shadow: 0 0 0 3px var(--p-olive-tint), 0 0 10px rgba(168, 184, 106, 0.4); }
  50% { box-shadow: 0 0 0 6px transparent, 0 0 18px rgba(168, 184, 106, 0.7); }
}

.painters {
  margin: 6px 0 0 19px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-4);
}

/* The two doors, under the room and above the table. */
.room-actions {
  grid-area: actions;
  justify-self: center;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: 6px;
}

.room-actions .p-button[aria-pressed='true'] {
  border-color: var(--p-gold);
  color: var(--p-gold);
}

/* The room: the painting of the andron behind, dimmed to lamplight and faded
   into the night at its edges; the Scribe at the head; the couches on either
   side by where their citizens stood; the question between them. */
.room-stage {
  grid-area: stage;
  position: relative;
  isolation: isolate;
  display: grid;
  grid-template-columns: minmax(0, 252px) minmax(0, 1fr) minmax(0, 252px);
  grid-template-areas:
    'left hint   right'
    'left head   right'
    'left matter right'
    'left mid    right'
    'left foot   right'
    'left rest   right';
  grid-template-rows: auto auto auto auto auto 1fr;
  column-gap: clamp(20px, 3.4vw, 56px);
  margin: 30px calc(-1 * var(--p-gutter)) 0;
  padding: 48px var(--p-gutter) 56px;
  min-width: 0;
}

.room-scene {
  position: absolute;
  inset: 0;
  z-index: -1;
  background:
    radial-gradient(ellipse 30% 34% at 50% 16%, rgba(240, 182, 96, 0.18), transparent 72%),
    radial-gradient(ellipse 78% 70% at 50% 46%, rgba(11, 14, 19, 0.5), rgba(11, 14, 19, 0.86) 76%, rgba(11, 14, 19, 0.97) 100%),
    url('/media/acts/symposium.jpg') center 74% / cover no-repeat;
  /* Faded into the night on every side: a room seen by lamplight, not a picture in a frame. */
  -webkit-mask-image:
    linear-gradient(180deg, transparent 0, #000 11%, #000 84%, transparent 100%),
    linear-gradient(90deg, transparent 0, #000 7%, #000 93%, transparent 100%);
  -webkit-mask-composite: source-in;
  mask-image:
    linear-gradient(180deg, transparent 0, #000 11%, #000 84%, transparent 100%),
    linear-gradient(90deg, transparent 0, #000 7%, #000 93%, transparent 100%);
  mask-composite: intersect;
  pointer-events: none;
}

.room-faces { display: contents; }

.room-hint {
  grid-area: hint;
  margin: 0 0 18px;
  text-align: center;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

/* The head of the table: the Scribe, larger, in her own lamplight. */
.seat-head {
  grid-area: head;
  position: relative;
  display: flex;
  justify-content: center;
}

.seat-head::before {
  content: '';
  position: absolute;
  top: -30px;
  left: 50%;
  width: 280px;
  height: 240px;
  transform: translateX(-50%);
  z-index: -1;
  background: radial-gradient(closest-side, rgba(240, 182, 96, 0.2), transparent);
  pointer-events: none;
}

/* A seat: a face on the couch, the name beneath, a pip for where they stood. */
.seat {
  position: relative;
  width: 118px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 6px 2px 8px;
  background: transparent;
  border: 0;
  color: var(--p-ink);
  font: inherit;
  text-align: center;
  cursor: pointer;
}

.seat.scribe { width: 180px; }

.seat-coin {
  position: relative;
  display: inline-flex;
  border-radius: var(--p-radius-coin);
  transition: transform 0.25s ease;
}

.seat .citizen-coin {
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.55);
  transition: box-shadow 0.25s ease, filter 0.3s ease;
}

.seat.scribe .citizen-coin {
  width: 116px;
  height: 116px;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--p-gold) 22%, transparent), 0 12px 36px rgba(0, 0, 0, 0.6);
}

.seat:hover .seat-coin { transform: translateY(-2px); }
.seat:hover .seat-name { color: var(--p-gold); }

.seat.seated .citizen-coin,
.seat.chosen .citizen-coin {
  box-shadow: 0 0 0 2px var(--p-bg), 0 0 0 4px var(--p-gold), 0 0 30px rgba(240, 182, 96, 0.42);
}

/* Chosen for the crowd: a small gold check on the coin. */
.seat.chosen .seat-coin::after {
  content: '';
  position: absolute;
  top: 0;
  right: 0;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--p-gold);
  box-shadow: 0 0 0 2px var(--p-bg);
  -webkit-mask: none;
}

.seat.chosen .seat-coin::before {
  content: '';
  position: absolute;
  top: 5px;
  right: 5px;
  z-index: 1;
  width: 12px;
  height: 12px;
  background: #1f1a16;
  -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M3 8.5l3.2 3L13 4.5' fill='none' stroke='black' stroke-width='2.4'/%3E%3C/svg%3E") center / contain no-repeat;
  mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath d='M3 8.5l3.2 3L13 4.5' fill='none' stroke='black' stroke-width='2.4'/%3E%3C/svg%3E") center / contain no-repeat;
}

/* Where they stood, as one pip on the coin's rim. */
.coin-pip {
  position: absolute;
  right: 5px;
  bottom: 5px;
  width: 13px;
  height: 13px;
  border-radius: 50%;
  box-shadow: 0 0 0 2px var(--p-bg);
  background: var(--p-ink-3);
}

.seat-coin.is-for .coin-pip { background: var(--p-olive); }
.seat-coin.is-against .coin-pip { background: var(--p-error); }
.seat-coin.is-between .coin-pip { background: var(--p-ink-3); }
.seat-coin.is-aside .coin-pip { background: var(--p-bg); box-shadow: 0 0 0 2px var(--p-bg), inset 0 0 0 2px var(--p-aegean); }

.seat-name {
  max-width: 100%;
  font-family: var(--p-font-display);
  font-size: 1.0625rem;
  font-weight: 600;
  line-height: 1.12;
  color: var(--p-ink);
  text-shadow: 0 1px 12px rgba(0, 0, 0, 0.85);
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  transition: color 0.2s ease;
}

.seat.scribe .seat-name { font-size: var(--t-xl); }

.seat-note {
  min-height: 1em;
  font-family: var(--p-font-inscription);
  font-size: 0.6875rem;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  line-height: 1.2;
  color: var(--p-ink-3);
}

.seat-note.lit { color: var(--p-gold); }
.seat-note:empty { display: none; }

/* Chosen for the crowd, the check on the coin says it; the words stay for listeners only. */
.seat.chosen .seat-note {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* Asleep: the citizens' faces stay on the couches, in shadow. The Scribe does not sleep. */
.symposium.asleep .seat:not(.scribe) .citizen-coin { filter: grayscale(0.6) brightness(0.7); }
.symposium.asleep .seat:not(.scribe) .seat-name { color: var(--p-ink-2); }

/* The couches */
.wing { min-width: 0; }
.wing.at-left { grid-area: left; }
.wing.at-right { grid-area: right; }
.wing.at-mid { grid-area: mid; margin-top: 26px; }
.wing.at-foot { grid-area: foot; margin-top: 22px; }
.wing.at-rest { grid-area: rest; margin-top: 22px; }

.wing-label {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-bottom: 12px;
  font-family: var(--p-font-inscription);
  font-size: 0.6875rem;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-2);
}

.wing-n {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-variant-numeric: lining-nums;
  line-height: 1;
  letter-spacing: 0;
  color: var(--p-ink-3);
}

.wing-faces {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 14px 16px;
}

.wing.at-left .wing-faces,
.wing.at-right .wing-faces { gap: 18px 16px; }

.wing-faces li {
  min-width: 0;
  animation: arrive 0.6s ease both;
}

.wing-faces li:nth-child(2) { animation-delay: 0.05s; }
.wing-faces li:nth-child(3) { animation-delay: 0.1s; }
.wing-faces li:nth-child(4) { animation-delay: 0.15s; }
.wing-faces li:nth-child(n + 5) { animation-delay: 0.2s; }

@keyframes arrive {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: none; }
}

/* Where they stood: a pip and a few words, coloured as the Web colours its ties. */
.stance {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-top: 3px;
  font-size: var(--t-xs);
  line-height: 1.3;
  color: var(--p-ink-3);
}

.stance-pip {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  border: 1px solid currentColor;
}

.is-for .stance-pip,
.is-yes .stance-pip { background: var(--p-olive); border-color: var(--p-olive); }
.stance.is-for { color: var(--p-olive-deep); }
.is-against .stance-pip,
.is-no .stance-pip { background: var(--p-error); border-color: var(--p-error); }
.stance.is-against { color: var(--p-error); }
.is-between .stance-pip,
.is-unsure .stance-pip { background: var(--p-ink-3); border-color: var(--p-ink-3); }
.is-aside .stance-pip { background: transparent; border-color: var(--p-aegean); }
.stance.is-aside { color: var(--p-aegean); }
.is-all .stance-pip,
.is-none .stance-pip { background: var(--p-gold); border-color: var(--p-gold); }
.is-silent .stance-pip { background: transparent; border-color: var(--p-ink-4); }

/* The question the couches stood for or against, once, beneath the Scribe. */
.room-matter {
  grid-area: matter;
  justify-self: center;
  max-width: 34em;
  margin-top: 22px;
  text-align: center;
}

.matter-text {
  margin: 8px 0 0;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.35;
  color: var(--p-ink);
  text-shadow: 0 1px 14px rgba(0, 0, 0, 0.9);
  text-wrap: balance;
}

.matter-text::before { content: '\201C'; }
.matter-text::after { content: '\201D'; }

/* The table */
.table {
  grid-area: table;
  justify-self: center;
  width: 100%;
  max-width: 920px;
  min-width: 0;
  margin-top: 34px;
  display: flex;
  flex-direction: column;
  scroll-margin-top: calc(var(--p-header-h) + 12px);
}

/* The caption band: the seated face, large, in candlelight. */
.table-band {
  --role: var(--p-gold);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 26px;
  align-items: start;
  padding-bottom: 20px;
}

/* Sitting down: the new face slides onto the couch. */
.seat-enter-active { transition: opacity 0.4s ease, transform 0.4s cubic-bezier(0.2, 0.7, 0.2, 1); }
.seat-enter-from { opacity: 0; transform: translateX(28px); }
.seat-leave-active { display: none; }

.band-face {
  position: relative;
  isolation: isolate;
  padding: 4px;
}

.band-face::before {
  content: '';
  position: absolute;
  inset: -26px;
  z-index: -1;
  border-radius: 50%;
  background: radial-gradient(closest-side, color-mix(in srgb, var(--role) 26%, transparent), transparent);
  pointer-events: none;
}

.band-text { min-width: 0; padding-top: 4px; }

.band-name {
  margin: 4px 0 2px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.05;
  color: var(--p-ink);
}

.band-name:focus { outline: none; }
.band-name:focus-visible { outline: 2px solid var(--p-gold); outline-offset: 4px; }

.band-role {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

.band-stance { margin: 6px 0 0; font-size: var(--t-sm); }

.band-quote {
  margin: 14px 0 0;
  padding-left: 16px;
  border-left: 2px solid var(--role);
  max-width: 44em;
}

.band-quote p {
  margin: 0;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.4;
  color: var(--p-ink);
}

.band-quote p::before { content: '\201C'; }
.band-quote p::after { content: '\201D'; }

.band-quote cite {
  display: block;
  margin-top: 6px;
  font-style: normal;
  font-size: var(--t-xs);
  color: var(--p-ink-4);
}

.band-saw { margin-top: 12px; }
.band-saw .band-line { margin-top: 4px; }

.saw-label {
  font-family: var(--p-font-inscription);
  font-size: 0.6875rem;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.band-line {
  margin: 8px 0 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  line-height: 1.55;
  color: var(--p-ink-2);
  max-width: 48em;
}

/* The Greek key under the band: the whole width of the table, faint, a divider. */
.table-rule {
  width: 100%;
  height: 12px;
  margin-bottom: 6px;
  opacity: 0.16;
}

/* The dialogue, set as a script: the visitor's line, then the answer under the speaker's name. */
.dialogue {
  list-style: none;
  margin: 0;
  padding: 22px 0 10px;
  display: flex;
  flex-direction: column;
  gap: 30px;
}

.dialogue-empty {
  padding: 22px 0 14px;
  text-align: center;
}

.dialogue-empty p {
  margin: 0 auto;
  max-width: 30em;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
}

.line { min-width: 0; animation: arrive 0.45s ease both; }

.line.asked {
  align-self: flex-end;
  width: fit-content;
  max-width: min(36em, 88%);
  padding-bottom: 12px;
  border-bottom: 1px solid color-mix(in srgb, var(--p-gold) 55%, transparent);
}

.asked-label { display: block; margin-bottom: 6px; }

.asked-text {
  margin: 0;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.4;
  color: var(--p-ink);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.line.answered {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.answered-body { min-width: 0; }

.line-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 10px;
  margin: 0 0 4px;
  min-height: 40px;
}

.line-who {
  font-family: var(--p-font-inscription);
  font-size: var(--t-sm);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink);
}

.line-who.working {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  color: var(--p-ink-3);
}

/* Hear it: a quiet voice button beside the speaker's name. */
.hear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  margin-left: auto;
  padding: 0;
  background: transparent;
  border: 1px solid transparent;
  color: var(--p-ink-3);
  cursor: pointer;
  transition: color 0.2s ease, border-color 0.2s ease;
}

.hear:hover { color: var(--p-gold); border-color: var(--p-line-strong); }
.hear.speaking { color: var(--p-gold); border-color: var(--p-gold); }

/* While a voice speaks: a small inscription under the name, the bars of the voice, and Stop. */
.voicing {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px 12px;
  margin: -2px 0 10px;
}

.voicing-state {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-gold);
}

.voicing-state.is-gathering { color: var(--p-ink-3); }

.voice-bars {
  display: inline-flex;
  align-items: flex-end;
  gap: 2px;
  height: 12px;
}

.voice-bars i {
  width: 2px;
  height: 100%;
  background: currentColor;
  transform-origin: bottom;
  transform: scaleY(0.4);
  animation: voice 1.1s ease-in-out infinite;
}

.voice-bars i:nth-child(2) { animation-delay: 0.18s; }
.voice-bars i:nth-child(3) { animation-delay: 0.36s; }
.voicing-state.is-gathering .voice-bars i { animation-name: gather; }

@keyframes voice {
  0%, 100% { transform: scaleY(0.35); }
  50% { transform: scaleY(1); }
}

@keyframes gather {
  0%, 100% { opacity: 0.35; transform: scaleY(0.35); }
  50% { opacity: 1; transform: scaleY(0.5); }
}

.voicing-stop { gap: 8px; padding-inline: 12px 14px; }

.stop-mark {
  width: 8px;
  height: 8px;
  background: currentColor;
}

.voicing-note {
  flex-basis: 100%;
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.45;
  color: var(--p-ink-3);
}

.voice-audio { display: none; }

.answered-text {
  font-family: var(--p-font-serif);
  font-size: 1.0625rem;
  line-height: 1.7;
  color: var(--p-ink-2);
  max-width: 62ch;
}

.answered-text :deep(p) { margin: 0 0 1em; }
.answered-text :deep(p:last-child) { margin-bottom: 0; }
.answered-text :deep(.md-h2),
.answered-text :deep(.md-h3),
.answered-text :deep(.md-h4),
.answered-text :deep(.md-h5) {
  font-family: var(--p-font-display);
  font-weight: 600;
  color: var(--p-ink);
  margin: 1.2em 0 0.5em;
}
.answered-text :deep(.md-h2) { font-size: var(--t-xl); }
.answered-text :deep(.md-h3) { font-size: var(--t-lg); }
.answered-text :deep(.md-h4),
.answered-text :deep(.md-h5) { font-size: var(--t-md); }
.answered-text :deep(.md-ul),
.answered-text :deep(.md-ol) { padding-left: 1.4em; margin: 0 0 1em; }
.answered-text :deep(li) { margin-bottom: 0.4em; }
.answered-text :deep(.md-quote) {
  margin: 1em 0;
  padding-left: 16px;
  border-left: 2px solid var(--p-gold);
  font-style: italic;
  color: var(--p-ink-3);
}
.answered-text :deep(strong) { color: var(--p-ink); font-weight: 600; }
.answered-text :deep(.code-block),
.answered-text :deep(.inline-code) {
  font-family: var(--p-font-mono);
  font-size: var(--t-xs);
  background: var(--p-surface-2);
  border: 1px solid var(--p-line);
}
.answered-text :deep(.code-block) { padding: 10px; overflow-x: auto; }
.answered-text :deep(.inline-code) { padding: 1px 4px; }
.answered-text :deep(.md-hr) { border: 0; border-top: 1px solid var(--p-line); margin: 1.2em 0; }

/* Thinking */
.ellipsis { display: inline-flex; gap: 5px; padding: 6px 0; }
.ellipsis.inline { padding: 0 0 0 8px; vertical-align: middle; }
.ellipsis i {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--p-ink-4);
  animation: breathe 1.2s ease-in-out infinite;
}
.ellipsis.inline i { width: 4px; height: 4px; }
.ellipsis i:nth-child(2) { animation-delay: 0.2s; }
.ellipsis i:nth-child(3) { animation-delay: 0.4s; }

@keyframes breathe {
  0%, 100% { opacity: 0.3; transform: translateY(0); }
  50% { opacity: 1; transform: translateY(-3px); }
}

/* The prompt row and the question */
.prompt {
  padding: 14px 0 12px;
}

.prompt.stuck {
  position: sticky;
  bottom: var(--p-way-h);
  z-index: 5;
  background: linear-gradient(180deg, transparent, var(--p-bg) 18px);
}

.asleep-note {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px 14px;
  margin: 0 0 12px;
  padding: 12px 14px;
  border: 1px solid var(--p-line);
  border-left: 2px solid var(--p-ink-4);
  background: var(--p-surface);
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-2);
}

.asleep-note span { flex: 1 1 18em; min-width: 0; }
.asleep-note .p-button { font-style: normal; }

/* Ask as Socrates would: the label, then the questions that can be put in the mouth. */
.socratic {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  margin-bottom: 10px;
  min-width: 0;
}

.socratic-label { flex: 0 0 auto; color: var(--p-ink-3); }

.socratic-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.prompt.stuck .socratic-chips {
  flex-wrap: nowrap;
  overflow-x: auto;
  overscroll-behavior-x: contain;
  padding: 3px 48px 6px 3px;
  margin-left: -3px;
  scrollbar-width: thin;
  scrollbar-color: var(--p-line-strong) transparent;
  -webkit-mask-image: linear-gradient(90deg, #000 calc(100% - 56px), transparent);
  mask-image: linear-gradient(90deg, #000 calc(100% - 56px), transparent);
}

.socratic-chip {
  flex: 0 0 auto;
  min-height: 40px;
  padding: 8px 12px;
  background: transparent;
  border: 1px solid var(--p-line-strong);
  color: var(--p-ink-2);
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  cursor: pointer;
  transition: border-color 0.2s ease, color 0.2s ease;
}

.prompt.stuck .socratic-chip { white-space: nowrap; }
.socratic-chip:hover:not(:disabled) { border-color: var(--p-gold); color: var(--p-gold); }
.socratic-chip:disabled { opacity: 0.5; cursor: not-allowed; }

.ask {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  align-items: end;
}

.ask-input {
  width: 100%;
  min-height: 48px;
  max-height: 200px;
  padding: 13px 16px;
  box-sizing: border-box;
  background: var(--p-surface);
  border: 1px solid var(--p-control-border);
  color: var(--p-ink);
  font-family: var(--p-font-body);
  font-size: var(--t-md);
  line-height: 1.4;
  resize: none;
}

.ask-input::placeholder { color: var(--p-ink-4); }
.ask-input { overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--p-line-strong) transparent; }
.ask-input:focus { outline: 2px solid var(--p-gold); outline-offset: 2px; }
.ask-input:disabled { opacity: 0.6; cursor: not-allowed; }
.ask-input[readonly] { color: var(--p-ink-3); }

.ask-send { min-width: 92px; }

/* The crowd */
.crowd-head { padding-bottom: 14px; }

.crowd-pick {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 16px;
  padding: 12px 0 6px;
}

.crowd-count {
  margin: 0;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-md);
  color: var(--p-ink-2);
}

.crowd-links { display: flex; gap: 4px; }

.faces {
  list-style: none;
  margin: 8px 0 16px;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
}

.face {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.face-name {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-weight: 600;
  color: var(--p-ink);
}

.crowd-ask { grid-template-columns: minmax(0, 1fr); }

.crowd-submit {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
}

.ask-reason {
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

/* While the crowd answers: their faces, breathing. */
.quorum-waiting {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px 14px;
  margin-top: 26px;
}

.q-waiting-faces {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
}

.q-waiting-faces li { margin-right: -6px; animation: breathe-face 1.8s ease-in-out infinite; }
.q-waiting-faces li:nth-child(3n + 2) { animation-delay: 0.3s; }
.q-waiting-faces li:nth-child(3n) { animation-delay: 0.6s; }

@keyframes breathe-face {
  0%, 100% { opacity: 0.55; }
  50% { opacity: 1; }
}

/* The quorum of faces */
.quorum {
  margin-top: 34px;
  padding-top: 24px;
  border-top: 1px solid var(--p-line);
  min-width: 0;
}

.quorum-summary {
  margin: 8px 0 6px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.15;
  color: var(--p-ink);
  text-wrap: balance;
  max-width: 30em;
}

.quorum-sub {
  margin: 0 0 16px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.answers-question {
  margin: 0 0 20px;
  padding-left: 16px;
  border-left: 2px solid var(--p-gold);
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.4;
  color: var(--p-ink);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.tally {
  display: flex;
  gap: 3px;
  height: 6px;
  margin: 0 0 20px;
}

.tally-part { flex-basis: 0; min-width: 6px; background: var(--p-ink-4); }
.tally-part.is-for,
.tally-part.is-yes { background: var(--p-olive); }
.tally-part.is-against,
.tally-part.is-no { background: var(--p-error); }
.tally-part.is-between,
.tally-part.is-unsure { background: var(--p-ink-3); }
.tally-part.is-aside { background: var(--p-aegean); }
.tally-part.is-all { background: var(--p-gold); }
.tally-part.is-silent { background: var(--p-surface-3); }

.q-groups {
  display: flex;
  flex-wrap: wrap;
  gap: 20px 34px;
}

.q-group { min-width: 0; max-width: 100%; }

.q-group-label {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-family: var(--p-font-inscription);
  font-size: 0.6875rem;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.q-group-n {
  font-family: var(--p-font-display);
  font-size: var(--t-md);
  font-variant-numeric: lining-nums;
  letter-spacing: 0;
  color: var(--p-ink);
}

.q-faces {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 4px;
}

.q-face {
  width: 68px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 6px 2px 4px;
  background: transparent;
  border: 1px solid transparent;
  color: var(--p-ink-3);
  font: inherit;
  cursor: pointer;
  animation: arrive 0.5s ease both;
  transition: border-color 0.2s ease, background 0.2s ease, color 0.2s ease;
}

.q-faces li:nth-child(2) .q-face { animation-delay: 0.05s; }
.q-faces li:nth-child(3) .q-face { animation-delay: 0.1s; }
.q-faces li:nth-child(4) .q-face { animation-delay: 0.15s; }
.q-faces li:nth-child(n + 5) .q-face { animation-delay: 0.2s; }

.q-face:hover { color: var(--p-ink); }
.q-face[aria-pressed='true'] { color: var(--p-gold); background: var(--p-surface-2); border-color: var(--p-line-strong); }
.q-face[aria-pressed='true'] .citizen-coin { box-shadow: 0 0 0 2px var(--p-bg), 0 0 0 4px var(--p-gold); }
.q-group.is-silent .q-face .citizen-coin { filter: saturate(0.4) brightness(0.75); }

.q-name {
  width: 100%;
  font-size: var(--t-xs);
  line-height: 1.2;
  text-align: center;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.q-name.long {
  white-space: normal;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}

.q-hint {
  margin: 12px 0 14px;
  font-size: var(--t-xs);
  color: var(--p-ink-4);
}

.q-voice {
  --role: var(--p-gold);
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  padding: 18px 20px 20px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  border-left: 2px solid var(--role);
  min-width: 0;
  scroll-margin: calc(var(--p-header-h) + 12px) 0 calc(var(--p-way-h) + 16px);
}

.q-voice .line-meta { margin-bottom: 0; }
.q-role { margin: 0 0 4px; font-size: var(--t-xs); line-height: 1.4; color: var(--p-ink-3); }
.q-voice .stance { margin: 2px 0 12px; }
.q-voice .answered-text { font-size: var(--t-md); }

.read-all { margin-top: 12px; padding-inline: 0; }

.reply-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 340px), 1fr));
  gap: 18px;
}

.reply {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 14px;
  align-items: start;
  padding: 18px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
  min-width: 0;
}

.reply .line-meta { min-height: 0; }
.reply .answered-text { font-size: var(--t-md); }

/* The Chronicle drawer */
.drawer-root {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  justify-content: flex-end;
}

.drawer-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(5, 7, 10, 0.72);
}

.chronicle {
  position: relative;
  width: min(760px, 100%);
  height: 100%;
  display: flex;
  flex-direction: column;
  box-shadow: var(--p-shadow-2);
  min-width: 0;
}

.chronicle-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px 10px 28px;
  border-bottom: 1px solid var(--p-line);
  background: var(--p-surface-2);
}

.chronicle-page {
  flex: 1;
  min-height: 0;
  overflow: auto;
  overscroll-behavior: contain;
  padding: 36px clamp(20px, 5vw, 56px) 64px;
}

.chronicle-title {
  margin: 0 0 14px;
  font-family: var(--p-font-display);
  font-size: var(--t-2xl);
  font-weight: 600;
  line-height: 1.08;
  color: var(--p-ink);
  text-wrap: balance;
}

.chronicle-summary {
  margin: 0 0 22px;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.5;
  color: var(--p-ink-3);
}

.chronicle-question { margin: 0 0 22px; }
.chronicle-question p {
  margin: 6px 0 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.6;
  color: var(--p-ink-2);
}

.chronicle-rule { width: 144px; margin: 0 0 30px; }

.chapter { margin-bottom: 40px; }

.chapter-title {
  margin: 6px 0 14px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.15;
  color: var(--p-ink);
}

.chapter-body {
  font-family: var(--p-font-serif);
  font-size: 1.0625rem;
  line-height: 1.75;
  color: var(--p-ink-2);
  max-width: 64ch;
}

.chapter-body :deep(p) { margin: 0 0 1em; }
.chapter-body :deep(.md-h2),
.chapter-body :deep(.md-h3),
.chapter-body :deep(.md-h4),
.chapter-body :deep(.md-h5) {
  font-family: var(--p-font-display);
  font-weight: 600;
  color: var(--p-ink);
  margin: 1.4em 0 0.5em;
}
.chapter-body :deep(.md-h3) { font-size: var(--t-lg); }
.chapter-body :deep(.md-h4),
.chapter-body :deep(.md-h5) { font-size: var(--t-md); }
.chapter-body :deep(.md-quote) {
  margin: 1.2em 0;
  padding-left: 18px;
  border-left: 2px solid var(--p-terracotta);
  font-style: italic;
  color: var(--p-ink-3);
}
.chapter-body :deep(.md-ul),
.chapter-body :deep(.md-ol) { padding-left: 1.4em; margin: 0 0 1em; }
.chapter-body :deep(strong) { color: var(--p-ink); font-weight: 600; }
.chapter-body :deep(.md-hr) { border: 0; border-top: 1px solid var(--p-line); margin: 1.4em 0; }
.chapter-body :deep(.code-block),
.chapter-body :deep(.inline-code) {
  font-family: var(--p-font-mono);
  font-size: var(--t-xs);
  background: var(--p-surface-2);
  border: 1px solid var(--p-line);
}

.chapter-pending,
.chronicle-waiting {
  font-family: var(--p-font-serif);
  font-style: italic;
  color: var(--p-ink-3);
}

.chronicle-link { margin-top: 8px; text-decoration: none; }

.drawer-enter-active,
.drawer-leave-active { transition: opacity 0.3s ease; }
.drawer-enter-active .chronicle,
.drawer-leave-active .chronicle { transition: transform 0.35s ease; }
.drawer-enter-from,
.drawer-leave-to { opacity: 0; }
.drawer-enter-from .chronicle,
.drawer-leave-to .chronicle { transform: translateX(40px); }

/* Phones and narrow rooms: one column. The couches become one strip of faces
   under the threshold, the doors come after them, and the table below. */
@media (max-width: 1023px) {
  .symposium {
    display: flex;
    flex-direction: column;
    padding-top: 4px;
  }

  /* The room's caption stays for listeners; on the screen the strip of faces
     follows the threshold directly, under its own line. */
  .room-head {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }

  .room-stage {
    display: flex;
    flex-direction: column;
    margin: 0 calc(-1 * var(--p-gutter)) 0;
    padding: 18px 0 20px;
  }

  .room-scene {
    background:
      linear-gradient(180deg, rgba(11, 14, 19, 0.8), rgba(11, 14, 19, 0.62) 45%, rgba(11, 14, 19, 0.92)),
      url('/media/acts/symposium.jpg') center 78% / cover no-repeat;
    -webkit-mask-image: linear-gradient(180deg, transparent 0, #000 14%, #000 86%, transparent 100%);
    -webkit-mask-composite: source-over;
    mask-image: linear-gradient(180deg, transparent 0, #000 14%, #000 86%, transparent 100%);
    mask-composite: add;
  }

  .room-hint {
    margin: 0 0 8px;
    padding-inline: var(--p-gutter);
    text-align: left;
  }

  /* The strip: every face in one row, swiped, each snapping to the edge. */
  .room-faces {
    display: flex;
    align-items: flex-start;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    scroll-snap-type: x proximity;
    scroll-padding-inline: var(--p-gutter);
    padding: 4px var(--p-gutter) 8px;
    scrollbar-width: none;
    -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 12px, #000 calc(100% - 40px), transparent);
    mask-image: linear-gradient(90deg, transparent 0, #000 12px, #000 calc(100% - 40px), transparent);
  }
  .room-faces::-webkit-scrollbar { display: none; }
  .room-faces::after { content: ''; flex: 0 0 24px; }

  .seat-head,
  .wing { flex: 0 0 auto; }
  .seat-head::before { top: -10px; width: 150px; height: 130px; }

  .wing,
  .wing.at-mid,
  .wing.at-foot,
  .wing.at-rest {
    margin: 0 0 0 12px;
    padding-left: 12px;
    border-left: 1px solid var(--p-line);
  }

  /* Each couch's name rides along the strip while its faces pass. */
  .wing-label {
    position: sticky;
    left: var(--p-gutter);
    width: max-content;
    justify-content: flex-start;
    margin: 0 0 6px 4px;
    white-space: nowrap;
  }

  .wing-faces,
  .wing.at-left .wing-faces,
  .wing.at-right .wing-faces {
    flex-wrap: nowrap;
    justify-content: flex-start;
    gap: 2px;
  }

  .wing-faces li { scroll-snap-align: start; }
  .seat-head { scroll-snap-align: start; padding-top: 24px; }

  .seat { width: 80px; gap: 6px; padding: 4px 2px 6px; }
  .seat.scribe { width: 84px; }
  .seat.scribe .citizen-coin { width: 64px; height: 64px; }
  .seat.scribe .seat-name { font-size: 1rem; }
  .seat-name { font-size: 0.9375rem; }
  .seat.scribe .seat-note { display: none; }
  .seat.scribe.seated .seat-note { display: block; }
  .coin-pip { right: 1px; bottom: 1px; width: 11px; height: 11px; }
  .seat.chosen .seat-coin::after { top: -3px; right: -3px; width: 20px; height: 20px; }
  .seat.chosen .seat-coin::before { top: 1px; right: 1px; }

  .room-matter {
    align-self: stretch;
    max-width: none;
    margin: 10px 0 0;
    padding-inline: var(--p-gutter);
    text-align: left;
  }

  .matter-text { font-size: var(--t-md); text-wrap: pretty; }

  .room-state { margin-top: 14px; max-width: none; text-align: left; }
  .room-state .city-state { justify-content: flex-start; }
  .room-state .painters { margin-left: 19px; }
  .room-actions { width: 100%; margin-top: 14px; }
  .room-actions .p-button { flex: 1 1 auto; min-width: 0; }

  .table { margin-top: 26px; }

  /* Ask as Socrates would, on its own line; the questions in one row beneath it. */
  .socratic { gap: 6px; }
  .socratic-chips,
  .prompt.stuck .socratic-chips {
    flex-wrap: nowrap;
    overflow-x: auto;
    overscroll-behavior-x: contain;
    margin-inline: calc(-1 * var(--p-gutter));
    padding: 2px var(--p-gutter) 4px;
    scrollbar-width: none;
    -webkit-mask-image: none;
    mask-image: none;
  }
  .socratic-chips::-webkit-scrollbar { display: none; }
  .socratic-chip { white-space: nowrap; }
}

@media (max-width: 599px) {
  .symposium { padding-inline: 16px; }
  .table-band { display: block; }
  .table-band::after { content: ''; display: block; clear: both; }
  .band-face { float: left; margin: 0 16px 6px 0; }
  .band-face::before { inset: -16px; }
  .band-text { padding-top: 6px; }
  .band-quote,
  .band-saw,
  .band-line { clear: both; }
  .band-saw .band-line { clear: none; }
  .band-quote p { font-size: var(--t-md); }
  .line.asked { max-width: 92%; }
  .asked-text { font-size: 1.125rem; }
  .line.answered { gap: 12px; }
  .answered-text { font-size: 1rem; }
  .ask-send { min-width: 72px; padding-inline: 14px; }
  .q-groups { gap: 16px 20px; }
  .q-face { width: 62px; }
  .q-voice { padding: 14px 14px 16px; gap: 12px; }
  .chronicle-bar { padding: 8px 8px 8px 16px; }
  .chronicle-page { padding: 28px 16px 56px; }
}

/* Under reduced motion everything is already in place: no arrivals, no breathing, no lamp, no slide. */
@media (prefers-reduced-motion: reduce) {
  .ellipsis i { animation: none; opacity: 0.7; }
  .voice-bars i { animation: none; opacity: 1; }
  .voice-bars i:nth-child(2) { transform: scaleY(0.8); }
  .voicing-state.is-gathering .voice-bars i { opacity: 0.6; }
  .seat-coin,
  .seat .citizen-coin,
  .seat-name,
  .q-face,
  .hear { transition: none; }
  .seat:hover .seat-coin { transform: none; }
  .wing-faces li,
  .line,
  .q-face,
  .q-waiting-faces li { animation: none; opacity: 1; transform: none; }
  .city-state.is-awake .city-lamp { animation: none; }
  .seat-enter-active { transition: none; }
  .seat-enter-from { opacity: 1; transform: none; }
  .drawer-enter-active,
  .drawer-leave-active,
  .drawer-enter-active .chronicle,
  .drawer-leave-active .chronicle { transition: none; }
}
</style>
