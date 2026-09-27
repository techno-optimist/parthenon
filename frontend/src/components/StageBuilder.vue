<template>
  <div class="stage-builder" :class="{ walking: mode === 'walk' }">
    <p class="visually-hidden" aria-live="polite">{{ announcement }}</p>

    <!-- The Oracle at the bema: she asks on the right, one question per screen; the visitor answers on the left -->
    <section v-if="mode === 'walk'" :id="walkIds.root" class="walk" :aria-label="$t('parthenon.builder.oracle.label')">
      <fieldset class="shell" :disabled="disabled">
        <div class="walk-grid" :class="{ telos: step >= SUMMARY }">
          <!-- The Oracle: her tripod on the stone, and what she asks -->
          <div class="walk-pythia">
            <div class="walk-pythia-plate" aria-hidden="true">
              <img
                class="walk-pythia-img"
                src="/media/scenes/pnyx-bema.jpg"
                alt=""
                width="2000"
                height="848"
                loading="lazy"
                decoding="async"
              />
              <span class="walk-pythia-shade"></span>
              <span class="walk-pythia-glow"></span>
            </div>
            <div class="walk-pythia-body">
              <div class="walk-pythia-sign">
                <svg class="walk-tripod" :viewBox="TRIPOD.viewBox" aria-hidden="true">
                  <path
                    v-for="p in tripodFull"
                    :key="p.id"
                    :d="p.d"
                    :class="{ 'walk-vapour': p.vapour, late: p.vapour === 'late' }"
                    :pathLength="p.vapour ? 1 : null"
                  />
                </svg>
                <p class="walk-oracle">
                  <span class="walk-delphi" lang="el" aria-hidden="true">ΔΕΛΦΟΙ</span>
                  <span class="walk-oracle-name">{{ $t('parthenon.builder.oracle.eyebrow') }}</span>
                </p>
              </div>
              <Transition name="speech" mode="out-in" @after-enter="onStepEntered">
                <div :key="step" class="walk-speech">
                  <h3 :id="walkIds.heading" class="walk-question" tabindex="-1">{{ questionText }}</h3>
                  <p class="walk-voice">{{ voiceText }}</p>
                </div>
              </Transition>
            </div>
          </div>

          <!-- The visitor's answers -->
          <div class="walk-answers">
            <div class="walk-head">
              <ol class="walk-marks" aria-hidden="true">
                <li v-for="(s, i) in STEPS" :key="s.id" :class="{ done: i < step, now: i === step }">
                  <span>{{ s.numeral }}</span>
                </li>
              </ol>
              <p class="walk-progress" :class="{ telos: step >= SUMMARY }">
                <span aria-hidden="true">{{ step >= SUMMARY ? 'ΤΕΛΟΣ' : progressText }}</span>
                <span class="visually-hidden">{{ progressAria }}</span>
              </p>
            </div>

            <Transition name="walk" mode="out-in">
              <div :key="step" class="walk-step" @keydown="onWalkKeydown">
                <!-- Α΄ Who takes the floor? -->
                <div v-if="stepId === 'who'" class="walk-body">
                  <p :id="walkIds.featured" class="chip-group-label">{{ $t('parthenon.builder.oracle.who.featured') }}</p>
                  <div class="chip-row" role="group" :aria-labelledby="walkIds.featured">
                    <button
                      v-for="f in featured"
                      :key="f.id"
                      type="button"
                      class="chip walk-chip"
                      :class="{ 'on-stage': !!speakerForFigure(f) }"
                      :aria-pressed="speakerForFigure(f) ? 'true' : 'false'"
                      :aria-describedby="describedBy('featured', `f:${f.id}`)"
                      :disabled="speakersFull && !speakerForFigure(f)"
                      @pointerenter="noteEnter($event, 'featured', `f:${f.id}`)"
                      @pointerleave="noteLeave('featured', `f:${f.id}`)"
                      @focus="noteOn('featured', `f:${f.id}`)"
                      @blur="noteLeave('featured', `f:${f.id}`)"
                      @click="toggleFigure(f)"
                    >
                      <span class="chip-coin" aria-hidden="true">{{ f.letter }}</span>
                      <span class="chip-name">{{ figureName(f, locale) }}</span>
                    </button>
                  </div>
                  <p :id="noteIds.featured" class="chip-note" :class="{ idle: !notes.featured }">
                    <template v-if="notes.featured">
                      <span class="chip-note-name" aria-hidden="true">{{ notes.featured.name }}</span>
                      <span v-if="notes.featured.when" class="chip-note-when">{{ notes.featured.when }}</span>{{ ' ' }}
                      <span class="chip-note-text">{{ notes.featured.text }}</span>
                    </template>
                    <template v-else>{{ $t('parthenon.builder.noteFigures') }}</template>
                  </p>

                  <button
                    type="button"
                    class="text-btn walk-more"
                    :aria-expanded="moreFiguresOpen ? 'true' : 'false'"
                    :aria-controls="walkIds.more"
                    @click="moreFiguresOpen = !moreFiguresOpen"
                  >
                    <span class="walk-more-mark" aria-hidden="true">{{ moreFiguresOpen ? '−' : '+' }}</span>
                    {{ moreFiguresOpen ? $t('parthenon.builder.oracle.who.fewer') : $t('parthenon.builder.oracle.who.more') }}
                  </button>
                  <div v-show="moreFiguresOpen" :id="walkIds.more" class="walk-more-body">
                    <div class="chip-row" role="group" :aria-label="$t('parthenon.builder.oracle.who.more')">
                      <button
                        v-for="f in others"
                        :key="f.id"
                        type="button"
                        class="chip walk-chip"
                        :class="{ 'on-stage': !!speakerForFigure(f) }"
                        :aria-pressed="speakerForFigure(f) ? 'true' : 'false'"
                        :aria-describedby="describedBy('more', `f:${f.id}`)"
                        :disabled="speakersFull && !speakerForFigure(f)"
                        @pointerenter="noteEnter($event, 'more', `f:${f.id}`)"
                        @pointerleave="noteLeave('more', `f:${f.id}`)"
                        @focus="noteOn('more', `f:${f.id}`)"
                        @blur="noteLeave('more', `f:${f.id}`)"
                        @click="toggleFigure(f, 'more')"
                      >
                        <span class="chip-coin" aria-hidden="true">{{ f.letter }}</span>
                        <span class="chip-name">{{ figureName(f, locale) }}</span>
                      </button>
                    </div>
                    <p :id="walkIds.guests" class="chip-group-label walk-sub-label">{{ $t('parthenon.builder.oracle.who.guests') }}</p>
                    <div class="chip-row" role="group" :aria-labelledby="walkIds.guests">
                      <button
                        v-for="g in modernGuests"
                        :key="g.id"
                        type="button"
                        class="chip walk-chip"
                        :class="{ 'on-stage': !!speakerForGuest(g) }"
                        :aria-pressed="speakerForGuest(g) ? 'true' : 'false'"
                        :aria-describedby="describedBy('more', `g:${g.id}`)"
                        :disabled="speakersFull && !speakerForGuest(g)"
                        @pointerenter="noteEnter($event, 'more', `g:${g.id}`)"
                        @pointerleave="noteLeave('more', `g:${g.id}`)"
                        @focus="noteOn('more', `g:${g.id}`)"
                        @blur="noteLeave('more', `g:${g.id}`)"
                        @click="toggleGuest(g)"
                      >
                        <span class="chip-coin modern" aria-hidden="true">{{ initialOf(guestName(g, locale)) }}</span>
                        <span class="chip-name">{{ guestName(g, locale) }}</span>
                      </button>
                    </div>
                    <p v-if="notes.more" :id="noteIds.more" class="chip-note">
                      <span class="chip-note-name" aria-hidden="true">{{ notes.more.name }}</span>
                      <span v-if="notes.more.when" class="chip-note-when">{{ notes.more.when }}</span>{{ ' ' }}
                      <span class="chip-note-text">{{ notes.more.text }}</span>
                    </p>
                  </div>

                  <div class="field walk-write">
                    <label :for="walkIds.name" class="field-label">{{ $t('parthenon.builder.oracle.who.writeLabel') }}</label>
                    <div class="walk-inline">
                      <input
                        :id="walkIds.name"
                        v-model="nameDraft"
                        type="text"
                        class="input"
                        maxlength="80"
                        autocomplete="off"
                        :disabled="speakersFull"
                        :placeholder="$t('parthenon.builder.oracle.who.writePlaceholder')"
                        :aria-describedby="shownProblems.length ? walkIds.problems : undefined"
                        @keydown.enter="onNameEnter"
                      />
                      <button type="button" class="p-button secondary walk-add" :disabled="!nameDraft.trim() || speakersFull" @click="addWrittenName">
                        {{ $t('parthenon.builder.oracle.who.add') }}
                      </button>
                    </div>
                  </div>

                  <div v-if="namedSpeakers.length" class="walk-floor">
                    <p :id="walkIds.floor" class="chip-group-label">{{ $t('parthenon.builder.oracle.who.onFloor') }}</p>
                    <ul class="walk-tokens" :aria-labelledby="walkIds.floor">
                      <li v-for="sp in namedSpeakers" :key="sp.key" class="walk-token">
                        <span class="chip-coin" :class="{ modern: !sp.figureId }" aria-hidden="true">{{ coinLetter(sp) }}</span>
                        <span class="walk-token-name">{{ speakerLabel(sp, locale) }}</span>
                        <button
                          :id="domId('wrm', sp.key)"
                          type="button"
                          class="walk-token-x"
                          :aria-label="$t('parthenon.builder.oracle.who.remove', { name: speakerLabel(sp, locale) })"
                          @click="walkRemoveSpeaker(sp)"
                        >
                          <span aria-hidden="true">×</span>
                        </button>
                      </li>
                    </ul>
                    <p class="walk-note">
                      {{ $t('parthenon.builder.oracle.who.formatNow', { format: $t(`parthenon.builder.oracle.formats.${stage.format}`) }) }}
                    </p>
                    <p v-if="speakersFull" class="walk-note">{{ $t('parthenon.builder.oracle.who.full', { max: MAX_SPEAKERS }) }}</p>
                  </div>
                  <p v-if="undo && undo.kind === 'speaker'" class="undo-line">
                    {{ $t('parthenon.builder.speakerRemoved', { name: undo.name }) }}
                    <button type="button" class="text-btn walk-undo" @click="walkUndo">{{ $t('parthenon.builder.undo') }}</button>
                  </p>
                </div>

                <!-- Β΄ When and where? -->
                <div v-else-if="stepId === 'where'" class="walk-body">
                  <p :id="walkIds.age" class="chip-group-label">{{ $t('parthenon.builder.oracle.where.ageLabel') }}</p>
                  <div class="walk-eras" role="radiogroup" :aria-labelledby="walkIds.age">
                    <label v-for="id in ERA_IDS" :key="id" class="walk-era">
                      <input
                        type="radio"
                        class="visually-hidden"
                        :name="walkIds.eraName"
                        :value="id"
                        :checked="stage.era === id"
                        @change="chooseEra(id)"
                      />
                      <span class="walk-era-card">
                        <span class="walk-era-year">{{ $t(`parthenon.builder.oracle.eras.${id}.year`) }}</span>
                        <span class="walk-era-name">{{ $t(`parthenon.builder.oracle.eras.${id}.name`) }}</span>
                      </span>
                    </label>
                  </div>

                  <div class="field">
                    <label :for="walkIds.place" class="field-label">{{ $t('parthenon.builder.oracle.where.placeLabel') }}</label>
                    <input
                      :id="walkIds.place"
                      v-model="stage.setting"
                      type="text"
                      class="input"
                      maxlength="300"
                      autocomplete="off"
                      :placeholder="$t('parthenon.builder.oracle.where.placePlaceholder')"
                      :aria-invalid="shownProblems.length ? 'true' : undefined"
                      :aria-describedby="shownProblems.length ? walkIds.problems : undefined"
                    />
                  </div>
                  <div class="chip-group">
                    <p :id="walkIds.places" class="chip-group-label">{{ $t('parthenon.builder.oracle.where.placesLabel') }}</p>
                    <div class="chip-row" role="group" :aria-labelledby="walkIds.places">
                      <button
                        v-for="p in places"
                        :key="p.id"
                        type="button"
                        class="chip plain walk-chip"
                        :class="{ 'on-stage': stage.setting.trim() === placeSetting(p, locale) }"
                        :aria-pressed="stage.setting.trim() === placeSetting(p, locale) ? 'true' : 'false'"
                        @click="choosePlace(p)"
                      >
                        {{ placeLabel(p, locale) }}
                      </button>
                    </div>
                  </div>
                </div>

                <!-- Γ΄ What do they say? -->
                <div v-else-if="stepId === 'words'" class="walk-body">
                  <div v-for="sp in namedSpeakers" :key="sp.key" class="field walk-words">
                    <label :for="domId('wwords', sp.key)" class="field-label walk-says">
                      <span class="chip-coin" :class="{ modern: !sp.figureId }" aria-hidden="true">{{ coinLetter(sp) }}</span>
                      {{ $t('parthenon.builder.oracle.words.says', { name: speakerLabel(sp, locale) }) }}
                    </label>
                    <textarea
                      :id="domId('wwords', sp.key)"
                      v-model="sp.words"
                      class="input walk-words-input"
                      rows="4"
                      maxlength="4000"
                      :aria-invalid="wordsProblemKeys.has(sp.key) ? 'true' : undefined"
                      :aria-describedby="`${domId('whint', sp.key)}${wordsProblemKeys.has(sp.key) ? ` ${walkIds.problems}` : ''}`"
                      @focus="onWordsFocus"
                      @mouseup="onWordsFocus"
                    ></textarea>
                    <p :id="domId('whint', sp.key)" class="field-help">{{ wordsHint(sp) }}</p>
                  </div>
                </div>

                <!-- Δ΄ Who listens? -->
                <div v-else-if="stepId === 'listeners'" class="walk-body">
                  <p :id="walkIds.groups" class="chip-group-label">{{ $t('parthenon.builder.oracle.listeners.suggested') }}</p>
                  <div class="chip-row" role="group" :aria-labelledby="walkIds.groups">
                    <button
                      v-for="g in featuredGroups"
                      :key="g.name"
                      type="button"
                      class="chip plain walk-chip"
                      :class="{ 'on-stage': isSeated(g.name) }"
                      :aria-pressed="isSeated(g.name) ? 'true' : 'false'"
                      :aria-describedby="describedBy('groups', `a:${g.name}`)"
                      :disabled="crowdFull && !isSeated(g.name)"
                      @pointerenter="noteEnter($event, 'groups', `a:${g.name}`)"
                      @pointerleave="noteLeave('groups', `a:${g.name}`)"
                      @focus="noteOn('groups', `a:${g.name}`)"
                      @blur="noteLeave('groups', `a:${g.name}`)"
                      @click="toggleGroup(g, 'groups')"
                    >
                      <span class="chip-plus" aria-hidden="true">{{ isSeated(g.name) ? '✓' : '+' }}</span>
                      <span class="chip-name">{{ audienceLabel(g.name, locale) }}</span>
                    </button>
                    <button
                      v-for="a in ownGroups"
                      :key="a.key"
                      type="button"
                      class="chip plain walk-chip on-stage"
                      aria-pressed="true"
                      :aria-describedby="describedBy('groups', `a:${a.name}`)"
                      @pointerenter="noteEnter($event, 'groups', `a:${a.name}`)"
                      @pointerleave="noteLeave('groups', `a:${a.name}`)"
                      @focus="noteOn('groups', `a:${a.name}`)"
                      @blur="noteLeave('groups', `a:${a.name}`)"
                      @click="toggleGroup(a, 'groups')"
                    >
                      <span class="chip-plus" aria-hidden="true">✓</span>
                      <span class="chip-name">{{ audienceLabel(a.name, locale) }}</span>
                    </button>
                  </div>
                  <p :id="noteIds.groups" class="chip-note" :class="{ idle: !notes.groups }">
                    <template v-if="notes.groups">
                      <span class="chip-note-name" aria-hidden="true">{{ notes.groups.name }}</span>
                      <span class="chip-note-text">{{ notes.groups.text }}</span>
                    </template>
                    <template v-else>{{ $t('parthenon.builder.noteGroups') }}</template>
                  </p>

                  <button
                    v-if="otherGroups.length"
                    type="button"
                    class="text-btn walk-more"
                    :aria-expanded="moreGroupsOpen ? 'true' : 'false'"
                    :aria-controls="walkIds.moreGroups"
                    @click="moreGroupsOpen = !moreGroupsOpen"
                  >
                    <span class="walk-more-mark" aria-hidden="true">{{ moreGroupsOpen ? '−' : '+' }}</span>
                    {{ moreGroupsOpen ? $t('parthenon.builder.oracle.listeners.fewer') : $t('parthenon.builder.oracle.listeners.more') }}
                  </button>
                  <div v-show="moreGroupsOpen" :id="walkIds.moreGroups" class="walk-more-body">
                    <div class="chip-row" role="group" :aria-label="$t('parthenon.builder.oracle.listeners.more')">
                      <button
                        v-for="g in otherGroups"
                        :key="g.name"
                        type="button"
                        class="chip plain walk-chip"
                        :class="{ 'on-stage': isSeated(g.name) }"
                        :aria-pressed="isSeated(g.name) ? 'true' : 'false'"
                        :aria-describedby="describedBy('moreGroups', `a:${g.name}`)"
                        :disabled="crowdFull && !isSeated(g.name)"
                        @pointerenter="noteEnter($event, 'moreGroups', `a:${g.name}`)"
                        @pointerleave="noteLeave('moreGroups', `a:${g.name}`)"
                        @focus="noteOn('moreGroups', `a:${g.name}`)"
                        @blur="noteLeave('moreGroups', `a:${g.name}`)"
                        @click="toggleGroup(g, 'moreGroups')"
                      >
                        <span class="chip-plus" aria-hidden="true">{{ isSeated(g.name) ? '✓' : '+' }}</span>
                        <span class="chip-name">{{ audienceLabel(g.name, locale) }}</span>
                      </button>
                    </div>
                    <p v-if="notes.moreGroups" :id="noteIds.moreGroups" class="chip-note">
                      <span class="chip-note-name" aria-hidden="true">{{ notes.moreGroups.name }}</span>
                      <span class="chip-note-text">{{ notes.moreGroups.text }}</span>
                    </p>
                  </div>

                  <div class="field walk-write">
                    <label :for="walkIds.group" class="field-label">{{ $t('parthenon.builder.oracle.listeners.ownLabel') }}</label>
                    <div class="walk-inline">
                      <input
                        :id="walkIds.group"
                        v-model="groupDraft"
                        type="text"
                        class="input"
                        maxlength="80"
                        autocomplete="off"
                        :disabled="crowdFull"
                        :placeholder="$t('parthenon.builder.oracle.listeners.ownPlaceholder')"
                        @keydown.enter="onGroupEnter"
                      />
                      <button type="button" class="p-button secondary walk-add" :disabled="!groupDraft.trim() || crowdFull" @click="addOwnGroup">
                        {{ $t('parthenon.builder.oracle.listeners.add') }}
                      </button>
                    </div>
                  </div>
                  <p v-if="!seatedCount" class="walk-note">{{ $t('parthenon.builder.oracle.listeners.cityAtLarge') }}</p>
                  <p v-if="crowdFull" class="walk-note">{{ $t('parthenon.builder.oracle.listeners.full', { max: MAX_AUDIENCE }) }}</p>
                  <p v-if="undo && undo.kind === 'listener'" class="undo-line">
                    {{ $t('parthenon.builder.listenerRemoved', { name: undo.name }) }}
                    <button type="button" class="text-btn walk-undo" @click="walkUndo">{{ $t('parthenon.builder.undo') }}</button>
                  </p>
                </div>

                <!-- Ε΄ What should Athens decide? -->
                <div v-else-if="stepId === 'question'" class="walk-body">
                  <label :for="walkIds.question" class="visually-hidden">{{ $t('parthenon.builder.oracle.question.inputLabel') }}</label>
                  <textarea
                    :id="walkIds.question"
                    v-model="stage.question"
                    class="input question-input walk-question-input"
                    rows="4"
                    maxlength="1500"
                    :aria-invalid="shownProblems.length ? 'true' : undefined"
                    :aria-describedby="shownProblems.length ? walkIds.problems : undefined"
                  ></textarea>
                  <div v-if="questionFrom !== 'suggestion'" class="add-row walk-row-tight">
                    <button type="button" class="text-btn walk-text-btn" @click="useOracleQuestion">
                      {{ $t('parthenon.builder.oracle.question.useOracle') }}
                    </button>
                  </div>
                  <div class="chip-group">
                    <p :id="walkIds.quarrels" class="chip-group-label">{{ $t(`parthenon.builder.oracle.question.quarrels.${eraKey}`) }}</p>
                    <div class="chip-row walk-quarrels" role="group" :aria-labelledby="walkIds.quarrels">
                      <button
                        v-for="q in quarrels"
                        :key="q.id"
                        type="button"
                        class="chip plain walk-chip walk-quarrel"
                        :class="{ 'on-stage': questionFrom === q.id }"
                        :aria-pressed="questionFrom === q.id ? 'true' : 'false'"
                        @click="useQuarrel(q)"
                      >
                        {{ quarrelText(q, locale) }}
                      </button>
                    </div>
                  </div>
                </div>

                <!-- The stage, held up as a small scroll -->
                <div v-else class="walk-body">
                  <article class="walk-scroll p-paper" :aria-labelledby="walkIds.scrollTitle">
                    <p class="p-eyebrow walk-scroll-eyebrow">
                      {{ $t('parthenon.builder.oracle.summary.eyebrow') }} · {{ $t(`parthenon.builder.oracle.formats.${stage.format}`) }}
                    </p>
                    <h4 :id="walkIds.scrollTitle" class="walk-scroll-title">{{ summaryTitle }}</h4>
                    <dl class="walk-rows">
                      <div v-for="row in summaryRows" :key="row.id" class="walk-row">
                        <dt>
                          <span>{{ row.label }}</span>
                          <button
                            type="button"
                            class="text-btn walk-change"
                            :aria-label="$t('parthenon.builder.oracle.summary.changeAria', { what: row.label })"
                            @click="goTo(row.step)"
                          >
                            {{ $t('parthenon.builder.oracle.summary.change') }}
                          </button>
                        </dt>
                        <dd v-if="row.id === 'words'">
                          <p v-for="w in row.words" :key="w.key" class="walk-said">
                            <strong>{{ w.name }}</strong>
                            <span v-if="w.text" class="walk-quote">“{{ w.text }}”</span>
                            <em v-else>{{ $t('parthenon.builder.oracle.summary.fromTeaching', { name: w.name }) }}</em>
                          </p>
                        </dd>
                        <dd v-else>{{ row.text }}</dd>
                      </div>
                    </dl>
                  </article>
                  <div v-if="summaryProblems.length" class="walk-problems walk-problems-list">
                    <p class="walk-problems-label">{{ $t('parthenon.builder.oracle.summary.notReady') }}</p>
                    <ul :id="walkIds.summaryProblems">
                      <li v-for="(p, i) in summaryProblems" :key="i">
                        <span>{{ p.text }}</span>
                        <button v-if="p.step != null" type="button" class="text-btn walk-text-btn" @click="goTo(p.step)">
                          {{ $t('parthenon.builder.oracle.summary.answer') }}
                        </button>
                      </li>
                    </ul>
                  </div>
                  <p v-if="taken" class="taken-line walk-taken" role="status">{{ $t('parthenon.builder.oracle.summary.taken') }}</p>
                </div>
              </div>
            </Transition>

            <div :id="walkIds.problems" class="walk-problems" :class="{ empty: !shownProblems.length }" aria-live="polite">
              <p v-for="(p, i) in shownProblems" :key="`${p.code}-${i}`">{{ problemText(p) }}</p>
            </div>

            <div class="walk-nav">
              <button v-if="step > 0" type="button" class="p-button ghost walk-back" @click="back">
                <span aria-hidden="true">←</span> {{ $t('parthenon.builder.oracle.back') }}
              </button>
              <span class="walk-nav-gap"></span>
              <span v-if="step < SUMMARY" class="walk-enter-hint" aria-hidden="true">{{ enterHint }}</span>
              <button
                v-if="step < SUMMARY"
                type="button"
                class="p-button walk-next"
                :aria-describedby="shownProblems.length ? walkIds.problems : undefined"
                @click="next"
              >
                {{ $t('parthenon.builder.oracle.next') }} <span aria-hidden="true">→</span>
              </button>
              <button
                v-else
                type="button"
                class="p-button walk-speak"
                :disabled="!canSpeak"
                :aria-describedby="summaryProblems.length ? walkIds.summaryProblems : undefined"
                @click="speak"
              >
                <svg class="walk-speak-scroll" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M19 17V5a2 2 0 0 0-2-2H4" />
                  <path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3" />
                </svg>
                {{ $t('parthenon.builder.oracle.speak') }} <span aria-hidden="true">↓</span>
              </button>
            </div>

            <div class="walk-foot">
              <button
                type="button"
                class="p-button ghost small walk-write-link"
                :aria-describedby="walkIds.writeHint"
                @click="openForm"
              >
                <svg class="walk-stylus" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M4 20l3.5-1 11-11a1.8 1.8 0 0 0-2.5-2.5l-11 11L4 20z" />
                  <path d="M14.5 7.5l2 2" />
                </svg>
                {{ $t('parthenon.builder.oracle.writeIt') }}
              </button>
              <span :id="walkIds.writeHint" class="walk-write-hint">{{ $t('parthenon.builder.oracle.writeItHint') }}</span>
              <span v-if="draftNote" class="draft-note">{{ draftNote }}</span>
            </div>
          </div>
        </div>
      </fieldset>
    </section>

    <div v-else class="form-mode">
    <div class="form-return">
      <button :id="walkIds.returnBtn" type="button" class="p-button secondary small" @click="returnToWalk">
        <svg class="walk-tripod small" :viewBox="TRIPOD.viewBox" aria-hidden="true">
          <path v-for="p in tripodSmall" :key="p.id" :d="p.d" />
        </svg>
        {{ $t('parthenon.builder.oracle.returnTo') }}
      </button>
      <p class="form-return-note">{{ $t('parthenon.builder.oracle.formIntro') }}</p>
    </div>

    <fieldset class="shell" :disabled="disabled">
      <!-- Α΄ The form -->
      <section class="part" :aria-labelledby="ids.form">
        <h3 :id="ids.form" class="part-label">
          <span class="part-numeral" aria-hidden="true">Α΄</span>
          <span>{{ $t('parthenon.builder.formLabel') }}</span>
        </h3>
        <p class="part-help">{{ $t('parthenon.builder.formHelp') }}</p>

        <div class="format-grid" role="radiogroup" :aria-labelledby="ids.form">
          <label v-for="f in FORMATS" :key="f.id" class="format-option">
            <input
              v-model="stage.format"
              type="radio"
              class="visually-hidden"
              :name="ids.formatName"
              :value="f.id"
            />
            <span class="format-card">
              <svg class="format-glyph" viewBox="0 0 48 28" aria-hidden="true">
                <path v-for="(d, i) in glyphs[f.id].paths" :key="`p${i}`" :d="d" />
                <circle v-for="(c, i) in glyphs[f.id].dots" :key="`c${i}`" :cx="c[0]" :cy="c[1]" r="1.7" />
              </svg>
              <span class="format-name">{{ localText(f, 'label', locale) }}</span>
              <span class="format-blurb">{{ localText(f, 'blurb', locale) }}</span>
              <span class="format-voices">{{ rangeText(f) }}</span>
            </span>
          </label>
        </div>
      </section>

      <!-- Β΄ When and where -->
      <section class="part" :aria-labelledby="ids.when">
        <h3 :id="ids.when" class="part-label">
          <span class="part-numeral" aria-hidden="true">Β΄</span>
          <span>{{ $t('parthenon.builder.whenLabel') }}</span>
        </h3>
        <p class="part-help">{{ $t('parthenon.builder.whenHelp') }}</p>

        <div class="pill-row" role="radiogroup" :aria-labelledby="ids.when">
          <label v-for="e in ERAS" :key="e.id" class="pill-option">
            <input
              v-model="stage.era"
              type="radio"
              class="visually-hidden"
              :name="ids.eraName"
              :value="e.id"
              @change="onEraChange(e)"
            />
            <span class="pill">{{ localText(e, 'label', locale) }}</span>
          </label>
        </div>

        <div class="field">
          <label :for="ids.setting" class="field-label">{{ $t('parthenon.builder.settingLabel') }}</label>
          <input
            :id="ids.setting"
            v-model="stage.setting"
            type="text"
            class="input"
            maxlength="300"
            autocomplete="off"
            :placeholder="$t('parthenon.builder.settingPlaceholder')"
            :aria-describedby="`${ids.setting}-help`"
          />
          <p :id="`${ids.setting}-help`" class="field-help">{{ $t('parthenon.builder.settingHelp') }}</p>
        </div>
      </section>

      <!-- Γ΄ The matter -->
      <section class="part" :aria-labelledby="ids.matter">
        <h3 :id="ids.matter" class="part-label">
          <span class="part-numeral" aria-hidden="true">Γ΄</span>
          <span>{{ $t('parthenon.builder.matterLabel') }}</span>
        </h3>
        <p class="part-help">{{ stage.era === 'now' ? $t('parthenon.builder.matterHelp') : $t('parthenon.builder.matterHelpAge') }}</p>

        <div class="field">
          <label :for="ids.topic" class="field-label">{{ $t('parthenon.builder.topicLabel') }}</label>
          <textarea
            :id="ids.topic"
            v-model="stage.topic"
            class="input"
            rows="5"
            maxlength="3000"
            :placeholder="topicPlaceholder"
          ></textarea>
        </div>

        <div v-if="showSparks && sparks.length" class="chip-group">
          <p :id="ids.sparks" class="chip-group-label">{{ sparksLabel }}</p>
          <div class="chip-row" role="group" :aria-labelledby="ids.sparks">
            <button
              v-for="s in sparks"
              :key="s.label"
              type="button"
              class="chip spark"
              :class="{ chosen: stage.topic.trim() === s.topic }"
              :aria-pressed="stage.topic.trim() === s.topic"
              @click="useSpark(s)"
            >
              {{ s.label }}
            </button>
          </div>
        </div>

        <div class="field">
          <label :for="ids.title" class="field-label">
            {{ $t('parthenon.builder.titleLabel') }}
            <span class="field-optional">{{ $t('parthenon.builder.optional') }}</span>
            <span v-if="marks.has('title')" class="oracle-tag" :title="$t('parthenon.builder.oracleTagTitle')">
              {{ $t('parthenon.builder.oracleTag') }}
            </span>
          </label>
          <input
            :id="ids.title"
            v-model="stage.title"
            type="text"
            class="input"
            maxlength="120"
            autocomplete="off"
            :placeholder="stage.title.trim() ? '' : titlePlaceholder"
            @input="unmark('title')"
          />
        </div>
      </section>

      <!-- Δ΄ The speakers -->
      <section class="part" :aria-labelledby="ids.speakers">
        <h3 :id="ids.speakers" class="part-label">
          <span class="part-numeral" aria-hidden="true">Δ΄</span>
          <span>{{ $t('parthenon.builder.speakersLabel') }}</span>
        </h3>
        <p class="part-help">{{ $t('parthenon.builder.speakersHelp') }}</p>

        <p class="range-line" :class="{ warn: rangeState !== 'ok' }">
          <template v-if="rangeState === 'under'">
            {{ $t('parthenon.builder.speakersUnder', { format: formatLabel, range: rangeText(currentFormat), missing: currentFormat.min - namedCount }) }}
          </template>
          <template v-else-if="rangeState === 'over'">
            {{ $t('parthenon.builder.speakersOver', { format: formatLabel, range: rangeText(currentFormat), extra: namedCount - currentFormat.max }) }}
          </template>
          <template v-else>
            {{ $t('parthenon.builder.speakersOk', { format: formatLabel, range: rangeText(currentFormat), named: namedCount }) }}
          </template>
        </p>

        <ol v-if="stage.speakers.length" class="speaker-list">
          <li
            v-for="(sp, i) in stage.speakers"
            :key="sp.key"
            class="speaker-editor"
            :class="{ open: openCards.has(sp.key) }"
          >
            <div class="speaker-head">
              <button
                :id="domId('toggle', sp.key)"
                type="button"
                class="speaker-toggle"
                :aria-expanded="openCards.has(sp.key) ? 'true' : 'false'"
                :aria-controls="domId('body', sp.key)"
                @click="toggleCard(sp)"
              >
                <span class="coin" :class="coinKind(sp)" aria-hidden="true"><span>{{ coinLetter(sp) }}</span></span>
                <span class="speaker-head-text">
                  <span class="speaker-head-name">{{ headName(sp) }}</span>
                  <span v-if="figureOf(sp)" class="speaker-head-greek">{{ figureOf(sp).greek }}</span>
                  <span v-if="sp.role.trim()" class="speaker-head-role">{{ headRole(sp) }}</span>
                </span>
                <span class="speaker-head-state">
                  <span v-if="marks.has(`words:${sp.key}`)" class="oracle-tag">{{ $t('parthenon.builder.oracleTag') }}</span>
                  <span class="word-count">{{ $t('parthenon.builder.wordCount', wordCount(sp.words)) }}</span>
                </span>
                <span class="chevron" aria-hidden="true"></span>
              </button>
              <div class="speaker-tools">
                <button
                  :id="domId('up', sp.key)"
                  type="button"
                  class="icon-btn"
                  :disabled="i === 0"
                  :aria-label="$t('parthenon.builder.moveUp', { name: displayName(sp) })"
                  :title="$t('parthenon.builder.moveUp', { name: displayName(sp) })"
                  @click="moveSpeaker(i, -1)"
                >
                  <span aria-hidden="true">↑</span>
                </button>
                <button
                  :id="domId('down', sp.key)"
                  type="button"
                  class="icon-btn"
                  :disabled="i === stage.speakers.length - 1"
                  :aria-label="$t('parthenon.builder.moveDown', { name: displayName(sp) })"
                  :title="$t('parthenon.builder.moveDown', { name: displayName(sp) })"
                  @click="moveSpeaker(i, 1)"
                >
                  <span aria-hidden="true">↓</span>
                </button>
                <button
                  type="button"
                  class="icon-btn remove"
                  :aria-label="$t('parthenon.builder.removeSpeaker', { name: displayName(sp) })"
                  :title="$t('parthenon.builder.removeSpeaker', { name: displayName(sp) })"
                  @click="removeSpeaker(i)"
                >
                  <span aria-hidden="true">×</span>
                </button>
              </div>
            </div>

            <div v-show="openCards.has(sp.key)" :id="domId('body', sp.key)" class="speaker-body">
              <div class="field">
                <label :for="domId('name', sp.key)" class="field-label">{{ $t('parthenon.builder.nameLabel') }}</label>
                <input
                  :id="domId('name', sp.key)"
                  v-model="sp.name"
                  type="text"
                  class="input"
                  maxlength="80"
                  autocomplete="off"
                  :placeholder="$t('parthenon.builder.namePlaceholder')"
                  @change="onNameChange(sp)"
                />
              </div>
              <div class="field">
                <label :for="domId('role', sp.key)" class="field-label">{{ $t('parthenon.builder.roleLabel') }}</label>
                <input
                  :id="domId('role', sp.key)"
                  v-model="sp.role"
                  type="text"
                  class="input"
                  maxlength="200"
                  autocomplete="off"
                  :placeholder="$t('parthenon.builder.rolePlaceholder')"
                />
              </div>
              <div class="field wide">
                <label :for="domId('ideas', sp.key)" class="field-label">{{ $t('parthenon.builder.ideasLabel') }}</label>
                <textarea
                  :id="domId('ideas', sp.key)"
                  v-model="sp.ideas"
                  class="input"
                  rows="4"
                  maxlength="1500"
                  :placeholder="$t('parthenon.builder.ideasPlaceholder')"
                ></textarea>
              </div>
              <div class="field wide">
                <label :for="domId('voice', sp.key)" class="field-label">{{ $t('parthenon.builder.voiceLabel') }}</label>
                <input
                  :id="domId('voice', sp.key)"
                  v-model="sp.voice"
                  type="text"
                  class="input"
                  maxlength="300"
                  autocomplete="off"
                  :placeholder="$t('parthenon.builder.voicePlaceholder')"
                />
              </div>
              <div class="field wide words">
                <button
                  type="button"
                  class="words-toggle"
                  :aria-expanded="wordsOpen.has(sp.key) ? 'true' : 'false'"
                  :aria-controls="domId('words', sp.key)"
                  @click="toggleWords(sp)"
                >
                  <span class="words-toggle-label">
                    {{ $t('parthenon.builder.wordsLabel') }}
                    <span v-if="marks.has(`words:${sp.key}`)" class="oracle-tag" :title="$t('parthenon.builder.oracleTagTitle')">
                      {{ $t('parthenon.builder.oracleTag') }}
                    </span>
                  </span>
                  <span class="word-count">{{ $t('parthenon.builder.wordCount', wordCount(sp.words)) }}</span>
                  <span class="chevron" aria-hidden="true"></span>
                </button>
                <div v-show="wordsOpen.has(sp.key)" class="words-panel">
                  <label :for="domId('words', sp.key)" class="visually-hidden">
                    {{ $t('parthenon.builder.wordsFor', { name: displayName(sp) }) }}
                  </label>
                  <textarea
                    :id="domId('words', sp.key)"
                    v-model="sp.words"
                    class="input words-input"
                    rows="8"
                    maxlength="4000"
                    :placeholder="$t('parthenon.builder.wordsPlaceholder')"
                    @input="unmark(`words:${sp.key}`)"
                  ></textarea>
                </div>
              </div>
            </div>
          </li>
        </ol>
        <p v-else class="empty-line">{{ $t('parthenon.builder.speakersEmpty') }}</p>

        <p v-if="undo && undo.kind === 'speaker'" class="undo-line">
          {{ $t('parthenon.builder.speakerRemoved', { name: undo.name }) }}
          <button type="button" class="text-btn" @click="undoRemove">{{ $t('parthenon.builder.undo') }}</button>
        </p>

        <div class="add-row">
          <button :id="ids.addSpeaker" type="button" class="add-btn" :disabled="speakersFull" @click="addOwnSpeaker">
            <span aria-hidden="true">+</span> {{ $t('parthenon.builder.addOwnSpeaker') }}
          </button>
          <span v-if="speakersFull" class="full-note">{{ $t('parthenon.builder.speakersFull', { max: MAX_SPEAKERS }) }}</span>
        </div>

        <div class="chip-group">
          <p :id="ids.summon" class="chip-group-label">{{ $t('parthenon.builder.summonLabel') }}</p>
          <div class="chip-row" role="group" :aria-labelledby="ids.summon">
            <button
              v-for="f in figures"
              :key="f.id"
              type="button"
              class="chip"
              :class="{ 'on-stage': !!speakerForFigure(f) }"
              :disabled="speakersFull && !speakerForFigure(f)"
              :aria-label="speakerForFigure(f) ? $t('parthenon.builder.onStageAria', { name: figureName(f, locale) }) : $t('parthenon.builder.summonAria', { name: figureName(f, locale) })"
              :aria-describedby="describedBy('formFigures', `f:${f.id}`)"
              @pointerenter="noteEnter($event, 'formFigures', `f:${f.id}`)"
              @pointerleave="noteLeave('formFigures', `f:${f.id}`)"
              @focus="noteOn('formFigures', `f:${f.id}`)"
              @blur="noteLeave('formFigures', `f:${f.id}`)"
              @click="noteChoose('formFigures', `f:${f.id}`, true); addFigure(f)"
            >
              <span class="chip-coin" aria-hidden="true">{{ f.letter }}</span>
              <span class="chip-name">{{ figureName(f, locale) }}</span>
              <span v-if="speakerForFigure(f)" class="chip-state" aria-hidden="true">{{ $t('parthenon.builder.onStage') }}</span>
            </button>
          </div>
          <p :id="noteIds.formFigures" class="chip-note" :class="{ idle: !notes.formFigures }">
            <template v-if="notes.formFigures">
              <span class="chip-note-name" aria-hidden="true">{{ notes.formFigures.name }}</span>
              <span v-if="notes.formFigures.when" class="chip-note-when">{{ notes.formFigures.when }}</span>{{ ' ' }}
              <span class="chip-note-text">{{ notes.formFigures.text }}</span>
            </template>
            <template v-else>{{ $t('parthenon.builder.noteFigures') }}</template>
          </p>
        </div>

        <div class="chip-group">
          <p :id="ids.invite" class="chip-group-label">{{ $t('parthenon.builder.inviteLabel') }}</p>
          <div class="chip-row" role="group" :aria-labelledby="ids.invite">
            <button
              v-for="g in modernGuests"
              :key="g.id"
              type="button"
              class="chip"
              :class="{ 'on-stage': !!speakerForGuest(g) }"
              :disabled="speakersFull && !speakerForGuest(g)"
              :aria-label="speakerForGuest(g) ? $t('parthenon.builder.onStageAria', { name: guestName(g, locale) }) : $t('parthenon.builder.inviteAria', { name: guestName(g, locale) })"
              :aria-describedby="describedBy('formGuests', `g:${g.id}`)"
              @pointerenter="noteEnter($event, 'formGuests', `g:${g.id}`)"
              @pointerleave="noteLeave('formGuests', `g:${g.id}`)"
              @focus="noteOn('formGuests', `g:${g.id}`)"
              @blur="noteLeave('formGuests', `g:${g.id}`)"
              @click="noteChoose('formGuests', `g:${g.id}`, true); addGuest(g)"
            >
              <span class="chip-coin modern" aria-hidden="true">{{ initialOf(guestName(g, locale)) }}</span>
              <span class="chip-name">{{ guestName(g, locale) }}</span>
              <span v-if="speakerForGuest(g)" class="chip-state" aria-hidden="true">{{ $t('parthenon.builder.onStage') }}</span>
            </button>
          </div>
          <p v-if="notes.formGuests" :id="noteIds.formGuests" class="chip-note">
            <span class="chip-note-name" aria-hidden="true">{{ notes.formGuests.name }}</span>
            <span class="chip-note-text">{{ notes.formGuests.text }}</span>
          </p>
        </div>
      </section>

      <!-- Ε΄ The crowd -->
      <section class="part" :aria-labelledby="ids.crowd">
        <h3 :id="ids.crowd" class="part-label">
          <span class="part-numeral" aria-hidden="true">Ε΄</span>
          <span>{{ $t('parthenon.builder.crowdLabel') }}</span>
        </h3>
        <p class="part-help">{{ $t('parthenon.builder.crowdHelp') }}</p>

        <template v-if="stage.audience.length">
          <div class="crowd-heads" aria-hidden="true">
            <span>{{ $t('parthenon.builder.crowdNameHead') }}</span>
            <span>{{ $t('parthenon.builder.crowdDescHead') }}</span>
          </div>
          <ul class="crowd-list">
            <li v-for="(a, i) in stage.audience" :key="a.key" class="crowd-row" :class="{ drafted: marks.has(`aud:${a.key}`) }">
              <div class="crowd-name">
                <label :for="domId('aname', a.key)" class="visually-hidden">
                  {{ $t('parthenon.builder.crowdNameAria', { n: i + 1 }) }}
                </label>
                <input
                  :id="domId('aname', a.key)"
                  v-model="a.name"
                  type="text"
                  class="input"
                  maxlength="80"
                  autocomplete="off"
                  :placeholder="$t('parthenon.builder.crowdNamePlaceholder')"
                  @input="unmark(`aud:${a.key}`)"
                />
                <span v-if="marks.has(`aud:${a.key}`)" class="oracle-tag" :title="$t('parthenon.builder.oracleTagTitle')">
                  {{ $t('parthenon.builder.oracleTag') }}
                </span>
              </div>
              <div class="crowd-desc">
                <label :for="domId('adesc', a.key)" class="visually-hidden">
                  {{ $t('parthenon.builder.crowdDescAria', { n: i + 1 }) }}
                </label>
                <textarea
                  :id="domId('adesc', a.key)"
                  v-model="a.description"
                  class="input"
                  rows="2"
                  maxlength="400"
                  :placeholder="$t('parthenon.builder.crowdDescPlaceholder')"
                  @input="unmark(`aud:${a.key}`)"
                ></textarea>
              </div>
              <button
                :id="domId('aremove', a.key)"
                type="button"
                class="icon-btn remove"
                :aria-label="$t('parthenon.builder.removeListener', { name: a.name.trim() || $t('parthenon.builder.unnamedGroup') })"
                :title="$t('parthenon.builder.removeListener', { name: a.name.trim() || $t('parthenon.builder.unnamedGroup') })"
                @click="removeListener(i)"
              >
                <span aria-hidden="true">×</span>
              </button>
            </li>
          </ul>
        </template>
        <p v-else class="empty-line">{{ $t('parthenon.builder.crowdEmpty') }}</p>

        <p v-if="undo && undo.kind === 'listener'" class="undo-line">
          {{ $t('parthenon.builder.listenerRemoved', { name: undo.name }) }}
          <button type="button" class="text-btn" @click="undoRemove">{{ $t('parthenon.builder.undo') }}</button>
        </p>

        <div class="add-row">
          <button :id="ids.addListener" type="button" class="add-btn" :disabled="crowdFull" @click="addOwnListener">
            <span aria-hidden="true">+</span> {{ $t('parthenon.builder.addOwnListener') }}
          </button>
          <span v-if="crowdFull" class="full-note">{{ $t('parthenon.builder.crowdFull', { max: MAX_AUDIENCE }) }}</span>
        </div>

        <div class="chip-group">
          <p :id="ids.presets" class="chip-group-label">
            {{ stage.era === 'ancient' ? $t('parthenon.builder.presetsAncient') : $t('parthenon.builder.presetsNow') }}
          </p>
          <div v-if="availablePresets.length" class="chip-row" role="group" :aria-labelledby="ids.presets">
            <button
              v-for="(p, i) in availablePresets"
              :id="domId('preset', i)"
              :key="p.name"
              type="button"
              class="chip plain"
              :disabled="crowdFull"
              :aria-label="$t('parthenon.builder.addPresetAria', { name: audienceLabel(p.name, locale) })"
              :aria-describedby="describedBy('formPresets', `a:${p.name}`)"
              @pointerenter="noteEnter($event, 'formPresets', `a:${p.name}`)"
              @pointerleave="noteLeave('formPresets', `a:${p.name}`)"
              @focus="noteOn('formPresets', `a:${p.name}`)"
              @blur="noteLeave('formPresets', `a:${p.name}`)"
              @click="noteChoose('formPresets', `a:${p.name}`, true); addPreset(p, i)"
            >
              <span class="chip-plus" aria-hidden="true">+</span>
              <span class="chip-name">{{ audienceLabel(p.name, locale) }}</span>
            </button>
          </div>
          <p v-else class="empty-line small">{{ $t('parthenon.builder.presetsAllAdded') }}</p>
          <p v-if="availablePresets.length" :id="noteIds.formPresets" class="chip-note" :class="{ idle: !notes.formPresets }">
            <template v-if="notes.formPresets">
              <span class="chip-note-name" aria-hidden="true">{{ notes.formPresets.name }}</span>
              <span class="chip-note-text">{{ notes.formPresets.text }}</span>
            </template>
            <template v-else>{{ $t('parthenon.builder.noteGroups') }}</template>
          </p>
        </div>
      </section>

      <!-- ΣΤ΄ The question put to the city -->
      <section class="part" :aria-labelledby="ids.question">
        <h3 :id="ids.question" class="part-label">
          <span class="part-numeral" aria-hidden="true">ΣΤ΄</span>
          <span :id="`${ids.question}-text`">{{ $t('parthenon.builder.questionLabel') }}</span>
          <span v-if="marks.has('question')" class="oracle-tag" :title="$t('parthenon.builder.oracleTagTitle')">
            {{ $t('parthenon.builder.oracleTag') }}
          </span>
        </h3>
        <p :id="`${ids.question}-help`" class="part-help">{{ $t('parthenon.builder.questionHelp') }}</p>

        <textarea
          :id="ids.questionInput"
          v-model="stage.question"
          class="input question-input"
          rows="5"
          maxlength="1500"
          :aria-labelledby="`${ids.question}-text`"
          :aria-describedby="`${ids.question}-help`"
          :placeholder="suggestedQuestion"
          @input="unmark('question')"
        ></textarea>
        <div v-if="!stage.question.trim()" class="add-row">
          <button type="button" class="text-btn" @click="useSuggestion">
            {{ $t('parthenon.builder.useSuggestion') }}
          </button>
        </div>

        <div class="field">
          <label :for="ids.next" class="field-label">
            {{ $t('parthenon.builder.nextLabel') }}
            <span class="field-optional">{{ $t('parthenon.builder.optional') }}</span>
            <span v-if="marks.has('happensNext')" class="oracle-tag" :title="$t('parthenon.builder.oracleTagTitle')">
              {{ $t('parthenon.builder.oracleTag') }}
            </span>
          </label>
          <textarea
            :id="ids.next"
            v-model="stage.happensNext"
            class="input"
            rows="2"
            maxlength="1500"
            :placeholder="defaultNextLine"
            :aria-describedby="`${ids.next}-help`"
            @input="unmark('happensNext')"
          ></textarea>
          <p :id="`${ids.next}-help`" class="field-help">{{ $t('parthenon.builder.nextHelp') }}</p>
        </div>
      </section>

      <!-- The altar: the Oracle, then the stage -->
      <section class="altar" :aria-labelledby="ids.altar">
        <h3 :id="ids.altar" class="visually-hidden">{{ $t('parthenon.builder.actionsLabel') }}</h3>

        <div class="oracle">
          <svg class="tripod" :viewBox="TRIPOD.viewBox" aria-hidden="true">
            <path v-for="p in tripodStill" :key="p.id" :d="p.d" :class="{ 'tripod-vapour': p.vapour }" />
          </svg>
          <div class="oracle-copy">
            <p class="oracle-eyebrow"><span aria-hidden="true">ΔΕΛΦΟΙ · </span>{{ $t('parthenon.builder.oracleEyebrow') }}</p>
            <p class="oracle-desc">{{ $t('parthenon.builder.oracleDesc') }}</p>
          </div>
          <button
            :id="ids.oracleBtn"
            type="button"
            class="oracle-btn"
            :disabled="!!oracleBlocker || oracle.pending"
            :aria-describedby="oracleBlocker && !oracle.pending ? ids.oracleWhy : undefined"
            @click="consultOracle"
          >
            {{ oracleLabel }}
          </button>
        </div>
        <p v-if="oracleBlocker && !oracle.pending" :id="ids.oracleWhy" class="oracle-why">{{ oracleBlocker }}</p>

        <div class="oracle-status" role="status" aria-live="polite">
          <template v-if="oracle.pending">
            <p class="vapour">{{ $t('parthenon.builder.oraclePending') }}</p>
            <p v-if="oracle.slow" class="oracle-sub">{{ $t('parthenon.builder.oracleSlow') }}</p>
            <button type="button" class="text-btn" @click="stopWaiting">{{ $t('parthenon.builder.oracleStop') }}</button>
          </template>
          <template v-else-if="oracle.result">
            <p class="oracle-spoke">{{ oracleSummary }}</p>
            <p v-if="oracleDrafted" class="oracle-sub">{{ $t('parthenon.builder.oracleReview') }}</p>
          </template>
        </div>
        <div v-if="oracle.error && !oracle.pending" class="oracle-error" role="alert">
          <p>{{ $t('parthenon.builder.oracleError', { message: oracle.error }) }}</p>
          <p class="oracle-sub">{{ $t('parthenon.builder.oracleErrorSafe') }}</p>
        </div>

        <div class="take">
          <div v-if="takeProblems.length" :id="ids.problems" class="problems">
            <p class="problems-label">{{ $t('parthenon.builder.problemsLabel') }}</p>
            <ul>
              <li v-for="(p, i) in takeProblems" :key="i">{{ p }}</li>
            </ul>
          </div>

          <button
            type="button"
            class="begin"
            :disabled="!canTake"
            :aria-describedby="takeProblems.length ? ids.problems : undefined"
            @click="takeStage"
          >
            <span>{{ $t('parthenon.builder.take') }}</span>
            <span class="begin-arrow" aria-hidden="true">↓</span>
          </button>
          <p v-if="taken" class="taken-line" role="status">
            {{ $t('parthenon.builder.taken') }}
          </p>

          <div v-if="hints.length" class="hints">
            <p class="hints-label">{{ $t('parthenon.builder.hintsLabel') }}</p>
            <ul>
              <li v-for="(h, i) in hints" :key="i">{{ h }}</li>
            </ul>
          </div>
        </div>

        <details class="preview" @toggle="previewOpen = $event.target.open">
          <summary>{{ $t('parthenon.builder.previewSummary') }}</summary>
          <template v-if="previewOpen">
            <article
              class="scroll-sheet p-paper"
              tabindex="0"
              role="region"
              :aria-label="$t('parthenon.scrollLabel')"
              v-html="previewHtml"
            ></article>
            <p class="scroll-note">
              <span>{{ $t('parthenon.builder.previewNote') }}</span>
              <button type="button" class="text-btn" @click="saveScroll">{{ $t('parthenon.builder.saveScroll') }}</button>
            </p>
          </template>
        </details>

        <div class="altar-foot">
          <span class="draft-note">{{ draftNote }}</span>
          <button type="button" class="text-btn quiet" :disabled="isPristine" @click="startOver">
            {{ $t('parthenon.builder.startOver') }}
          </button>
        </div>
      </section>
    </fieldset>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { draftStage } from '../api/parthenon.js'
import { audiencePresets } from '../parthenon/audiences.js'
import {
  ERAS,
  FORMATS,
  composeStageSeed,
  emptyAudienceMember,
  emptySpeaker,
  defaultNext,
  emptyStage,
  speakerFromFigure,
  stageHints,
  stageProblems,
} from '../parthenon/composeStage.js'
import { localText } from '../parthenon/localText.js'
import { figures, modernGuests } from '../parthenon/roster.js'
import {
  ERA_IDS,
  LAST_NUMERAL,
  STEPS,
  SUMMARY,
  TRIPOD,
  allProblems,
  audienceLabel,
  audienceLine,
  audienceSuggestions,
  blankSpeakers,
  clampStep,
  defaultAudience,
  defaultSetting,
  featuredFigures,
  figureForName,
  figureLine,
  figureName,
  firstBlank,
  firstOpenStep,
  fitFormat,
  guestLine,
  guestName,
  hasBlank,
  isDefaultAudience,
  isOfferedSetting,
  isUntouchedTemplate,
  joinNames as joinOracleNames,
  knowsNothingOf,
  localSetting,
  mattersFor,
  moreFigures,
  placeLabel,
  placeSetting,
  placesFor,
  quarrelQuestion,
  quarrelsFor,
  quarrelText,
  questionSource,
  questionToOffer,
  speakerLabel,
  stepProblems,
  suggestQuestionFor,
  templateFills,
  tripodMark,
} from '../parthenon/oracle.js'

const props = defineProps({
  disabled: { type: Boolean, default: false },
})

/**
 * use-stage: { file: File, fileName, markdown, question, title, era, stage }
 */
const emit = defineEmits(['use-stage'])

const { t, te, tm, rt, locale } = useI18n()

// Strings newer than the locale files fall back to this English until they are added there.
const tx = (key, fallback, params = {}) => {
  const full = `parthenon.builder.${key}`
  if (te(full) || te(full, 'en')) return t(full, params)
  return fallback.replace(/\{(\w+)\}/g, (_, name) => (params[name] != null ? String(params[name]) : ''))
}

const STORAGE_KEY = 'parthenon.stageDraft.v1'
const MAX_SPEAKERS = Math.max(...FORMATS.map((f) => f.max))
const MAX_AUDIENCE = 24
const ORACLE_CROWD = 8 // below this many groups the Oracle gathers more

// The Oracle's tripod, drawn from one set of lines at every size.
const tripodFull = tripodMark('full')
const tripodStill = tripodMark('still')
const tripodSmall = tripodMark('small')

// ---------------------------------------------------------------------------
// Ids

const uid = String(useId() || 'sb').replace(/[^A-Za-z0-9_-]/g, '')
const ids = {
  form: `${uid}-form`,
  formatName: `${uid}-format`,
  when: `${uid}-when`,
  eraName: `${uid}-era`,
  setting: `${uid}-setting`,
  matter: `${uid}-matter`,
  topic: `${uid}-topic`,
  sparks: `${uid}-sparks`,
  title: `${uid}-title`,
  speakers: `${uid}-speakers`,
  addSpeaker: `${uid}-add-speaker`,
  summon: `${uid}-summon`,
  invite: `${uid}-invite`,
  crowd: `${uid}-crowd`,
  addListener: `${uid}-add-listener`,
  presets: `${uid}-presets`,
  question: `${uid}-question`,
  questionInput: `${uid}-question-input`,
  next: `${uid}-next`,
  altar: `${uid}-altar`,
  oracleBtn: `${uid}-oracle-btn`,
  oracleWhy: `${uid}-oracle-why`,
  problems: `${uid}-problems`,
}
const domId = (part, key) => `${uid}-${part}-${key}`

// ---------------------------------------------------------------------------
// Small helpers

const str = (value) => (typeof value === 'string' ? value : '')
const norm = (value) => str(value).trim().replace(/\s+/g, ' ').toLowerCase()
const asMessage = (value) => {
  if (typeof value === 'string') return value
  try {
    return rt(value)
  } catch {
    return ''
  }
}
const wordCount = (text) => {
  const trimmed = str(text).trim()
  return trimmed ? trimmed.split(/\s+/).length : 0
}
const initialOf = (name) => {
  const bare = str(name).trim().replace(/^the\s+/i, '')
  return bare ? bare.charAt(0).toUpperCase() : '·'
}
const joinNames = (names) => {
  try {
    return new Intl.ListFormat(locale.value, { style: 'long', type: 'conjunction' }).format(names)
  } catch {
    return names.join(', ')
  }
}

// A speaker's name as the scroll will print it. Mirrors composeStage's plainLine:
// Markdown markers and a trailing ':;,' go, so '-', '**' or '---' is no name at all.
const LEAD_MARKER = /^\s*(?:#+|>+|[-*+•](?=\s|$))\s*/
const RULE_LINE = /^[-=_*~\s]{3,}$/
const bareLine = (line) => {
  let out = line
  for (let i = 0; i < 50; i++) {
    const next = out.replace(LEAD_MARKER, '')
    if (next === out) break
    out = next
  }
  return RULE_LINE.test(out) ? '' : out.replace(/[ \u00a0]+/g, ' ').trim()
}
const speakerName = (sp) => {
  const lines = str(sp && sp.name)
    .replace(/`/g, '')
    .replace(/\t/g, ' ')
    .replace(/[\u0000-\u0008\u000e-\u001f\u007f\u200b-\u200d\ufeff]/g, '')
    .split(/\r\n?|[\n\u000b\u000c\u0085\u2028\u2029]/)
    .map(bareLine)
  return bareLine(lines.join('\n').trim().replace(/\*+/g, '').replace(/\s+/g, ' ')).replace(/[\s:;,]+$/, '')
}

const prefersReducedMotion = () => {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

const figureById = (id) => figures.find((f) => f.id === id) || null
const guestById = (id) => modernGuests.find((g) => g.id === id) || null
const eraById = (id) => ERAS.find((e) => e.id === id) || null

// ---------------------------------------------------------------------------
// Stage state, restored from and saved to this browser

function normalizeStage(raw) {
  const base = emptyStage()
  const src = raw && typeof raw === 'object' ? raw : {}
  const seen = new Set()
  const freshKey = (key) => {
    const k = str(key)
    if (!k || seen.has(k)) return ''
    seen.add(k)
    return k
  }
  const era = eraById(src.era) ? src.era : base.era
  const speakers = (Array.isArray(src.speakers) ? src.speakers : [])
    .filter((s) => s && typeof s === 'object')
    .slice(0, MAX_SPEAKERS)
    .map((s) => {
      const sp = emptySpeaker({
        key: freshKey(s.key),
        name: str(s.name),
        role: str(s.role),
        ideas: str(s.ideas),
        voice: str(s.voice),
        words: str(s.words),
        figureId: figureById(s.figureId) ? s.figureId : null,
        guestId: guestById(s.guestId) ? s.guestId : null,
      })
      seen.add(sp.key)
      return sp
    })
  const audience = (Array.isArray(src.audience) ? src.audience : [])
    .filter((a) => a && typeof a === 'object')
    .slice(0, MAX_AUDIENCE)
    .map((a) => {
      const member = emptyAudienceMember({
        key: freshKey(a.key),
        name: str(a.name),
        description: str(a.description),
      })
      seen.add(member.key)
      return member
    })
  return {
    title: str(src.title),
    format: FORMATS.some((f) => f.id === src.format) ? src.format : base.format,
    era,
    setting: typeof src.setting === 'string' ? src.setting : eraById(era).setting,
    topic: str(src.topic),
    speakers,
    audience,
    question: str(src.question),
    happensNext: str(src.happensNext),
  }
}

function readDraft() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    const saved = parsed && typeof parsed === 'object' && parsed.stage ? parsed.stage : parsed
    return saved && typeof saved === 'object' ? normalizeStage(saved) : null
  } catch {
    return null
  }
}

const pristineCheck = (s) => {
  const base = emptyStage()
  return (
    !s.speakers.length &&
    !s.audience.length &&
    !s.title.trim() &&
    !s.topic.trim() &&
    !s.question.trim() &&
    !s.happensNext.trim() &&
    s.format === base.format &&
    s.era === base.era &&
    s.setting.trim() === base.setting
  )
}

const restored = readDraft()
const stage = reactive(restored || emptyStage())
const isPristine = computed(() => pristineCheck(stage))

// 'none' | 'restored' | 'saved'
const draftState = ref(restored && !pristineCheck(restored) ? 'restored' : 'none')
let saveTimer = null

function saveDraft() {
  clearTimeout(saveTimer)
  saveTimer = null
  try {
    if (pristineCheck(stage)) {
      window.localStorage.removeItem(STORAGE_KEY)
      draftState.value = 'none'
    } else {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, savedAt: Date.now(), stage }))
      draftState.value = 'saved'
    }
  } catch {
    // Storage may be full, blocked or missing; the builder works without it.
  }
}

function flushSave() {
  if (saveTimer) saveDraft()
}

watch(
  stage,
  () => {
    clearTimeout(saveTimer)
    saveTimer = setTimeout(saveDraft, 400)
  },
  { deep: true }
)

const draftNote = computed(() => {
  if (draftState.value === 'restored') return t('parthenon.builder.draftRestored')
  if (draftState.value === 'saved' && !isPristine.value) return t('parthenon.builder.draftSaved')
  return ''
})

function replaceStage(next) {
  Object.assign(stage, next)
}

// UI state that is not saved
const openCards = reactive(new Set())
const wordsOpen = reactive(new Set())
const marks = reactive(new Set()) // parts drafted by the Oracle and not yet edited
const announcement = ref('')
const undo = ref(null)
const taken = ref('')
const previewOpen = ref(false)

function resetUiFor(s) {
  openCards.clear()
  wordsOpen.clear()
  marks.clear()
  for (const sp of s.speakers) {
    if (!sp.name.trim()) openCards.add(sp.key)
    if (sp.words.trim()) wordsOpen.add(sp.key)
  }
}
resetUiFor(stage)

function unmark(key) {
  if (marks.has(key)) marks.delete(key)
}

function announce(text) {
  announcement.value = ''
  nextTick(() => {
    announcement.value = text
  })
}

function focusById(id, { scroll = false } = {}) {
  nextTick(() => {
    const el = document.getElementById(id)
    if (!el) return
    if (scroll) el.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'center' })
    el.focus({ preventScroll: scroll })
  })
}

// ---------------------------------------------------------------------------
// Α΄ form and Β΄ era

const glyphs = (() => {
  const column = (cx) => [`M${cx - 4} 6h8`, `M${cx - 2.5} 8v13M${cx + 2.5} 8v13`, `M${cx - 4} 23h8`]
  const arc = (cx, cy, r, n) =>
    Array.from({ length: n }, (_, k) => {
      const a = Math.PI - (k * Math.PI) / (n - 1)
      return [+(cx + r * Math.cos(a)).toFixed(2), +(cy - r * Math.sin(a)).toFixed(2)]
    })
  return {
    speech: { paths: column(24), dots: [] },
    dialogue: { paths: [...column(15), ...column(33)], dots: [] },
    panel: { paths: ['M3 3.5h42', 'M3 25.5h42', ...column(8), ...column(19), ...column(29), ...column(40)], dots: [] },
    trial: {
      paths: [
        'M24 4v20M17 24h14M10 8h28',
        'M10 8 6 17M10 8l4 9M6 17a4 2.5 0 0 0 8 0',
        'M38 8l-4 9M38 8l4 9M34 17a4 2.5 0 0 0 8 0',
      ],
      dots: [[24, 4]],
    },
    assembly: { paths: ['M21 21h6v5h-6z'], dots: [...arc(24, 25, 18, 7), ...arc(24, 25, 11, 5)] },
  }
})()

const currentFormat = computed(() => FORMATS.find((f) => f.id === stage.format) || FORMATS[0])
const formatLabel = computed(() => localText(currentFormat.value, 'label', locale.value))

function rangeText(f) {
  if (f.min === f.max) {
    return f.min === 1 ? t('parthenon.builder.voicesOne') : t('parthenon.builder.voicesExact', { count: f.min })
  }
  return t('parthenon.builder.voicesRange', { min: f.min, max: f.max })
}

const settingIsUnedited = () => {
  const current = stage.setting.trim()
  return !current || ERAS.some((e) => e.setting && e.setting === current) || isOfferedSetting(current)
}

function onEraChange(era) {
  if (settingIsUnedited()) stage.setting = defaultSetting(era.id, locale.value) || era.setting
}

// ---------------------------------------------------------------------------
// Γ΄ matter

// Today's quarrels live in the locale files; every other age takes the Oracle's
// quarrels of that age, so 399 BC is never offered the quarrels of 2026.
const sparks = computed(() => {
  if (stage.era !== 'now') return mattersFor(stage.era, locale.value)
  const list = tm('parthenon.builder.sparks')
  if (!Array.isArray(list)) return []
  return list
    .map((item) => ({ label: asMessage(item && item.label), topic: asMessage(item && item.topic) }))
    .filter((s) => s.label && s.topic)
})
const sparksLabel = computed(() =>
  stage.era === 'now' ? t('parthenon.builder.sparksLabel') : t(`parthenon.builder.sparksLabelAge.${eraKey.value}`)
)
const topicPlaceholder = computed(() =>
  stage.era === 'now' ? t('parthenon.builder.topicPlaceholder') : t(`parthenon.builder.topicPlaceholderAge.${eraKey.value}`)
)

const showSparks = computed(() => {
  const topic = stage.topic.trim()
  return !topic || sparks.value.some((s) => s.topic === topic)
})

function useSpark(spark) {
  stage.topic = spark.topic
}

// ---------------------------------------------------------------------------
// Δ΄ speakers

const namedSpeakers = computed(() => stage.speakers.filter((s) => speakerName(s)))
const namedCount = computed(() => namedSpeakers.value.length)
// The Oracle keeps only the first speaker of each name (as the backend does).
const oracleSpeakers = computed(() => {
  const seen = new Set()
  return namedSpeakers.value.filter((s) => {
    const key = norm(speakerName(s))
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
})
// Names worn by more than one speaker: the graph could not tell them apart.
const repeatedNames = computed(() => {
  const counts = new Map()
  for (const s of namedSpeakers.value) {
    const key = norm(speakerName(s))
    const entry = counts.get(key) || { name: speakerName(s), count: 0 }
    entry.count += 1
    counts.set(key, entry)
  }
  return [...counts.values()].filter((e) => e.count > 1).map((e) => e.name)
})
const speakersFull = computed(() => stage.speakers.length >= MAX_SPEAKERS)
const rangeState = computed(() => {
  if (namedCount.value < currentFormat.value.min) return 'under'
  if (namedCount.value > currentFormat.value.max) return 'over'
  return 'ok'
})

const figureOf = (sp) => (sp.figureId ? figureById(sp.figureId) : null)
const displayName = (sp) => sp.name.trim() || t('parthenon.builder.unnamedSpeaker')
// A card's head in the visitor's language: a roster figure or guest by their
// translated name and line while the visitor has not rewritten them. The fields
// below keep the English record the scroll is written from.
const headName = (sp) => (sp.name.trim() ? speakerLabel(sp, locale.value) || sp.name.trim() : t('parthenon.builder.unnamedSpeaker'))
function headRole(sp) {
  const role = sp.role.trim()
  if (!String(locale.value).startsWith('zh')) return role
  const figure = figureOf(sp)
  if (figure && figure.zh && role === speakerFromFigure(figure).role) {
    return [figure.zh.known, [figure.zh.lived, figure.zh.from].filter(Boolean).join('，')].filter(Boolean).join(' ')
  }
  const guest = sp.guestId ? guestById(sp.guestId) : null
  if (guest && guest.zh && role === guest.role) return guest.zh.role
  return role
}
const coinKind = (sp) => (sp.figureId ? 'ancient' : sp.guestId ? 'modern' : 'own')
const coinLetter = (sp) => (figureOf(sp) ? figureOf(sp).letter : initialOf(sp.name))

const speakerForFigure = (f) =>
  stage.speakers.find((s) => s.figureId === f.id) ||
  stage.speakers.find((s) => !s.figureId && norm(s.name) === norm(f.name)) ||
  null

const speakerForGuest = (g) =>
  stage.speakers.find((s) => s.guestId === g.id) ||
  stage.speakers.find((s) => !s.guestId && !s.figureId && norm(s.name) === norm(g.name)) ||
  null

// A card renamed to someone else is no longer the roster figure or guest it came from.
const rosterKey = (name) => norm(name).replace(/^the /, '')
function onNameChange(sp) {
  const name = norm(sp.name)
  const figure = figureOf(sp)
  if (figure && !name.includes(rosterKey(figure.name))) sp.figureId = null
  const guest = sp.guestId ? guestById(sp.guestId) : null
  if (guest && !name.includes(rosterKey(guest.name))) sp.guestId = null
}

function revealSpeaker(sp) {
  openCards.add(sp.key)
  focusById(domId('name', sp.key), { scroll: true })
}

function pushSpeaker(sp) {
  undo.value = null
  stage.speakers.push(sp)
  openCards.add(sp.key)
  if (sp.words.trim()) wordsOpen.add(sp.key)
  announce(t('parthenon.builder.announceAdded', { name: displayName(sp) }))
}

function addFigure(f) {
  const existing = speakerForFigure(f)
  if (existing) return revealSpeaker(existing)
  if (speakersFull.value) return
  pushSpeaker(speakerFromFigure(f))
}

function addGuest(g) {
  const existing = speakerForGuest(g)
  if (existing) return revealSpeaker(existing)
  if (speakersFull.value) return
  pushSpeaker(emptySpeaker({ name: g.name, role: g.role, ideas: g.ideas, voice: g.voice, guestId: g.id }))
}

function addOwnSpeaker() {
  if (speakersFull.value) return
  const sp = emptySpeaker({ guestId: null })
  pushSpeaker(sp)
  focusById(domId('name', sp.key))
}

function toggleCard(sp) {
  if (openCards.has(sp.key)) openCards.delete(sp.key)
  else openCards.add(sp.key)
}

function toggleWords(sp) {
  if (wordsOpen.has(sp.key)) wordsOpen.delete(sp.key)
  else {
    wordsOpen.add(sp.key)
    focusById(domId('words', sp.key))
  }
}

function moveSpeaker(index, delta) {
  const target = index + delta
  const list = stage.speakers
  if (target < 0 || target >= list.length) return
  const [sp] = list.splice(index, 1)
  list.splice(target, 0, sp)
  announce(t('parthenon.builder.announceMoved', { name: displayName(sp), position: target + 1 }))
  nextTick(() => {
    const same = document.getElementById(domId(delta < 0 ? 'up' : 'down', sp.key))
    const other = document.getElementById(domId(delta < 0 ? 'down' : 'up', sp.key))
    ;(same && !same.disabled ? same : other)?.focus()
  })
}

function removeSpeaker(index) {
  const sp = stage.speakers[index]
  if (!sp) return
  stage.speakers.splice(index, 1)
  openCards.delete(sp.key)
  const wasWordsOpen = wordsOpen.delete(sp.key)
  const wasMarked = marks.delete(`words:${sp.key}`)
  undo.value = { kind: 'speaker', item: sp, index, name: displayName(sp), wasWordsOpen, wasMarked }
  announce(t('parthenon.builder.announceRemoved', { name: displayName(sp) }))
  const next = stage.speakers[index] || stage.speakers[index - 1]
  focusById(next ? domId('toggle', next.key) : ids.addSpeaker)
}

// ---------------------------------------------------------------------------
// Ε΄ crowd

const crowdFull = computed(() => stage.audience.length >= MAX_AUDIENCE)
const presetPool = computed(() => audiencePresets[stage.era === 'ancient' ? 'ancient' : 'now'] || [])
const availablePresets = computed(() => {
  const present = new Set(stage.audience.map((a) => norm(a.name)).filter(Boolean))
  return presetPool.value.filter((p) => !present.has(norm(p.name)))
})

function addPreset(preset, index) {
  if (crowdFull.value) return
  undo.value = null
  stage.audience.push(emptyAudienceMember({ name: preset.name, description: preset.description }))
  announce(t('parthenon.builder.announceJoined', { name: preset.name }))
  // The chip disappears; keep focus in the chip row.
  nextTick(() => {
    const remaining = availablePresets.value.length
    if (remaining && !crowdFull.value) focusById(domId('preset', Math.min(index, remaining - 1)))
    else focusById(ids.addListener)
  })
}

function addOwnListener() {
  if (crowdFull.value) return
  undo.value = null
  const member = emptyAudienceMember()
  stage.audience.push(member)
  focusById(domId('aname', member.key))
}

function removeListener(index) {
  const member = stage.audience[index]
  if (!member) return
  stage.audience.splice(index, 1)
  const wasMarked = marks.delete(`aud:${member.key}`)
  const name = member.name.trim() || t('parthenon.builder.unnamedGroup')
  undo.value = { kind: 'listener', item: member, index, name, wasMarked }
  announce(t('parthenon.builder.announceLeft', { name }))
  const next = stage.audience[index] || stage.audience[index - 1]
  focusById(next ? domId('aremove', next.key) : ids.addListener)
}

function undoRemove() {
  const u = undo.value
  if (!u) return
  undo.value = null
  if (u.kind === 'speaker') {
    if (speakersFull.value) return
    stage.speakers.splice(Math.min(u.index, stage.speakers.length), 0, u.item)
    openCards.add(u.item.key)
    if (u.wasWordsOpen) wordsOpen.add(u.item.key)
    if (u.wasMarked) marks.add(`words:${u.item.key}`)
    announce(t('parthenon.builder.announceAdded', { name: u.name }))
    focusById(domId('toggle', u.item.key))
  } else {
    if (crowdFull.value) return
    stage.audience.splice(Math.min(u.index, stage.audience.length), 0, u.item)
    if (u.wasMarked) marks.add(`aud:${u.item.key}`)
    announce(t('parthenon.builder.announceJoined', { name: u.name }))
    focusById(domId('aname', u.item.key))
  }
}

// ---------------------------------------------------------------------------
// ΣΤ΄ question, and the seed it all becomes

const preview = computed(() => composeStageSeed(stage))
// The Oracle's question and the default next line, in the visitor's language.
const suggestedQuestion = computed(() => suggestQuestionFor(stage, locale.value))
const defaultNextLine = computed(() => (stage.happensNext.trim() ? '' : defaultNext(stage.format, locale.value)))
const titlePlaceholder = computed(() => (String(locale.value).startsWith('zh') ? summaryTitle.value : preview.value.title))

function useSuggestion() {
  stage.question = suggestedQuestion.value
  // The button goes away once the question is filled; keep focus on the question.
  focusById(ids.questionInput)
}

const problems = computed(() => {
  const blanks = blankSpeakers(stage)
  return [
    ...stageProblems(stage, locale.value),
    ...repeatedNames.value.map((name) =>
      tx('problemRepeatedName', 'More than one speaker is called {name}. Give each speaker a name of their own.', { name })
    ),
    ...(blanks.length ? [t('parthenon.builder.oracle.problems.formBlank', { names: joinNames(blanks) })] : []),
  ]
})
const hints = computed(() =>
  stageHints(stage, locale.value, {
    suggestion: suggestedQuestion.value,
    nameOf: (s) => speakerLabel(s, locale.value),
  })
)

// Same rules as the scroll renderer on the home page.
const escapeHtml = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const inline = (text) =>
  escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
const renderScroll = (markdown) => {
  const html = []
  for (const block of markdown.trim().split(/\n{2,}/)) {
    const lines = block.split('\n')
    if (lines.every((l) => l.startsWith('- '))) {
      html.push(`<ul>${lines.map((l) => `<li>${inline(l.slice(2))}</li>`).join('')}</ul>`)
      continue
    }
    for (const line of lines) {
      if (line.startsWith('## ')) html.push(`<h4>${inline(line.slice(3))}</h4>`)
      else if (line.startsWith('# ')) html.push(`<h3>${inline(line.slice(2))}</h3>`)
    }
    const prose = lines.filter((l) => !l.startsWith('#')).join(' ')
    if (prose) html.push(`<p>${inline(prose)}</p>`)
  }
  return html.join('')
}
const previewHtml = computed(() => (previewOpen.value ? renderScroll(preview.value.markdown) : ''))

function saveScroll() {
  const seed = preview.value
  try {
    const url = URL.createObjectURL(new Blob([seed.markdown], { type: 'text/markdown' }))
    const link = document.createElement('a')
    link.href = url
    link.download = seed.fileName
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 4000)
  } catch {
    // Nothing to do: the preview above still shows the whole scroll.
  }
}

function takeStage() {
  if (!canTake.value) return
  const seed = composeStageSeed(stage)
  const file = new File([seed.markdown], seed.fileName, { type: 'text/markdown' })
  flushSave()
  taken.value = seed.fileName
  emit('use-stage', {
    file,
    fileName: seed.fileName,
    markdown: seed.markdown,
    // A question left blank goes down as the Oracle's, in the visitor's language.
    question: stage.question.trim() ? seed.question : suggestedQuestion.value,
    title: seed.title,
    era: stage.era,
    stage: JSON.parse(JSON.stringify(stage)),
  })
}

// ---------------------------------------------------------------------------
// The Oracle

const oracle = reactive({ pending: false, slow: false, error: '', result: null })
let oracleToken = 0
let slowTimer = null
let alive = true

// Drafts that land after the stage is taken would miss the scroll, so Take waits for the Oracle.
const takeProblems = computed(() =>
  oracle.pending
    ? [
        ...problems.value,
        tx('problemOraclePending', 'The Oracle is still drafting. Wait for her answer, or stop waiting, before you take the stage.'),
      ]
    : problems.value
)
const canTake = computed(() => !props.disabled && takeProblems.value.length === 0)

const oracleLabel = computed(() => {
  if (oracle.pending) return t('parthenon.builder.oracleConsulting')
  return oracle.error ? t('parthenon.builder.oracleRetry') : t('parthenon.builder.oracleConsult')
})

// Groups the backend will see: named, first of each name.
const oracleCrowd = computed(() => {
  const seen = new Set()
  return stage.audience.filter((a) => {
    const key = norm(a.name)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
})

const oracleBlocker = computed(() => {
  if (!namedCount.value) return t('parthenon.builder.oracleNeedsSpeaker')
  if (!stage.topic.trim() && !stage.question.trim()) return t('parthenon.builder.oracleNeedsMatter')
  const somethingEmpty =
    oracleSpeakers.value.some((s) => !s.words.trim()) ||
    oracleCrowd.value.length < ORACLE_CROWD ||
    !stage.question.trim() ||
    !stage.title.trim() ||
    !stage.happensNext.trim()
  if (!somethingEmpty) return t('parthenon.builder.oracleNothingToFill')
  return ''
})

function oraclePayload() {
  return {
    title: stage.title.trim(),
    format: stage.format,
    era: stage.era,
    setting: stage.setting.trim(),
    topic: stage.topic.trim(),
    speakers: oracleSpeakers.value.map((s) => ({
      name: speakerName(s),
      role: s.role.trim(),
      ideas: s.ideas.trim(),
      voice: s.voice.trim(),
      words: s.words.trim(),
    })),
    audience: oracleCrowd.value.map((a) => ({ name: a.name.trim(), description: a.description.trim() })),
    question: stage.question.trim(),
    happensNext: stage.happensNext.trim(),
  }
}

// What a draft depends on. If it changes while the Oracle thinks, her answer no longer fits.
const stageSignature = () => JSON.stringify([stage.format, stage.era, norm(stage.setting), norm(stage.topic)])
const speakerSignature = (s) => JSON.stringify([norm(speakerName(s)), norm(s.role), norm(s.ideas), norm(s.voice)])

// Fill only what is still empty now: the user may have kept writing while the Oracle thought.
function mergeDraft(data, sent) {
  const d = data && typeof data === 'object' ? data : {}
  const summary = { words: [], audience: 0, title: false, question: false, happensNext: false, discarded: [], stale: false }

  // A new form, era, setting or matter: every draft was written for another stage.
  if (sent && sent.stage !== stageSignature()) {
    summary.stale = true
    return summary
  }

  for (const item of Array.isArray(d.speakers) ? d.speakers : []) {
    const words = str(item && item.words).trim()
    const name = norm(item && item.name)
    if (!words || !name) continue
    const asked = sent ? sent.speakers.find((e) => e.id === name) : null
    const sp = asked
      ? stage.speakers.find((s) => s.key === asked.key)
      : stage.speakers.find((s) => norm(speakerName(s)) === name)
    if (asked && (!sp || speakerSignature(sp) !== asked.signature)) {
      // Renamed, rewritten or removed while the Oracle thought.
      if (!summary.discarded.includes(asked.name)) summary.discarded.push(asked.name)
      continue
    }
    if (!sp || sp.words.trim()) continue
    sp.words = words
    wordsOpen.add(sp.key)
    marks.add(`words:${sp.key}`)
    summary.words.push(speakerName(sp))
  }

  const usedNames = new Set([...stage.audience.map((a) => norm(a.name)), ...stage.speakers.map((s) => norm(speakerName(s)))])
  usedNames.delete('')
  for (const item of Array.isArray(d.audience) ? d.audience : []) {
    if (stage.audience.length >= MAX_AUDIENCE) break
    const name = str(item && item.name).trim()
    if (!name || usedNames.has(norm(name))) continue
    usedNames.add(norm(name))
    const member = emptyAudienceMember({ name, description: str(item && item.description).trim() })
    stage.audience.push(member)
    marks.add(`aud:${member.key}`)
    summary.audience += 1
  }

  for (const part of ['title', 'question', 'happensNext']) {
    const value = str(d[part]).trim()
    if (value && !stage[part].trim()) {
      stage[part] = value
      marks.add(part)
      summary[part] = true
    }
  }
  return summary
}

async function consultOracle() {
  if (oracle.pending || oracleBlocker.value || props.disabled) return
  const token = ++oracleToken
  oracle.pending = true
  oracle.slow = false
  oracle.error = ''
  oracle.result = null
  clearTimeout(slowTimer)
  slowTimer = setTimeout(() => {
    if (token === oracleToken) oracle.slow = true
  }, 25000)
  const sent = {
    stage: stageSignature(),
    speakers: oracleSpeakers.value.map((s) => ({
      key: s.key,
      id: norm(speakerName(s)),
      name: speakerName(s),
      signature: speakerSignature(s),
    })),
  }
  try {
    const res = await draftStage(oraclePayload())
    if (token !== oracleToken || !alive) return
    oracle.result = mergeDraft(res && res.data, sent)
  } catch (err) {
    if (token !== oracleToken || !alive) return
    oracle.error = str(err && err.message).trim() || t('parthenon.builder.oracleUnknownError')
  } finally {
    if (token === oracleToken) {
      oracle.pending = false
      oracle.slow = false
      clearTimeout(slowTimer)
    }
  }
}

function stopWaiting() {
  oracleToken += 1
  clearTimeout(slowTimer)
  oracle.pending = false
  oracle.slow = false
  // This button goes away with the wait; hand focus back to the Oracle's own button.
  nextTick(() => {
    const btn = document.getElementById(ids.oracleBtn)
    if (btn && !btn.disabled) btn.focus()
  })
}

const oracleDrafted = computed(() => {
  const r = oracle.result
  return !!r && (r.words.length > 0 || r.audience > 0 || r.title || r.question || r.happensNext)
})

const oracleSummary = computed(() => {
  const r = oracle.result
  if (!r) return ''
  if (r.stale) {
    return tx(
      'oracleStale',
      'The stage changed while the Oracle thought, so her drafts no longer fit and nothing was filled in. Consult her again.'
    )
  }
  const parts = []
  if (r.words.length) parts.push(t('parthenon.builder.oraclePartWords', { names: joinNames(r.words) }))
  if (r.audience) parts.push(t('parthenon.builder.oraclePartAudience', r.audience))
  if (r.question) parts.push(t('parthenon.builder.oraclePartQuestion'))
  if (r.title) parts.push(t('parthenon.builder.oraclePartTitle'))
  if (r.happensNext) parts.push(t('parthenon.builder.oraclePartNext'))
  const lines = []
  if (parts.length) lines.push(t('parthenon.builder.oracleSpoke', { parts: parts.join('; ') }))
  if (r.discarded.length) {
    lines.push(
      tx('oracleDiscarded', 'Opening words drafted for {names} were set aside, because their details changed while she thought.', {
        names: joinNames(r.discarded),
      })
    )
  }
  return lines.length ? lines.join(' ') : t('parthenon.builder.oracleNothingNew')
})

// ---------------------------------------------------------------------------
// The Oracle at the bema: the same stage, asked one question at a time.
// The pure rules (steps, validity, offers by age) live in parthenon/oracle.js.

const WALK_KEY = 'parthenon.stageOracle.v1'
const walkIds = {
  root: `${uid}-walk`,
  heading: `${uid}-walk-q`,
  problems: `${uid}-walk-problems`,
  summaryProblems: `${uid}-walk-summary-problems`,
  featured: `${uid}-walk-featured`,
  more: `${uid}-walk-more`,
  guests: `${uid}-walk-guests`,
  name: `${uid}-walk-name`,
  floor: `${uid}-walk-floor`,
  age: `${uid}-walk-age`,
  eraName: `${uid}-walk-era`,
  place: `${uid}-walk-place`,
  places: `${uid}-walk-places`,
  groups: `${uid}-walk-groups`,
  moreGroups: `${uid}-walk-more-groups`,
  group: `${uid}-walk-group`,
  question: `${uid}-walk-question`,
  quarrels: `${uid}-walk-quarrels`,
  scrollTitle: `${uid}-walk-scroll-title`,
  returnBtn: `${uid}-walk-return`,
  writeHint: `${uid}-walk-write-hint`,
}

function readWalk() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(WALK_KEY) || 'null')
    return saved && typeof saved === 'object' ? saved : null
  } catch {
    return null
  }
}

const savedWalk = pristineCheck(stage) ? null : readWalk()
// 'walk' (the Oracle's questions) or 'form' (write it yourself)
const mode = ref(savedWalk && savedWalk.mode === 'form' ? 'form' : 'walk')
const step = ref(savedWalk ? Math.min(clampStep(savedWalk.step), firstOpenStep(stage)) : 0)
// The Oracle seats a crowd once; if the visitor sends every group away, it stays empty.
const seated = ref(!!(savedWalk && savedWalk.seated))
// The last question the Oracle wrote into the box, so an untouched one can follow the names.
const lastOffered = ref(savedWalk && typeof savedWalk.offered === 'string' ? savedWalk.offered : '')

watch([mode, step, seated, lastOffered], () => {
  try {
    window.localStorage.setItem(
      WALK_KEY,
      JSON.stringify({ mode: mode.value, step: step.value, seated: seated.value, offered: lastOffered.value })
    )
  } catch {
    // The conversation works without storage; it just starts at the beginning next time.
  }
})

const attempted = ref(false)
const nameDraft = ref('')
const groupDraft = ref('')
const moreFiguresOpen = ref(false)
const moreGroupsOpen = ref(false)
let focusOnEnter = false

// The Oracle's line about a chip, shown under its row: the chip under the mouse
// or the keyboard, else the one last chosen. It replaces the old title tooltips,
// which touch and keyboard never reached and which spoke English in Chinese.
// The chip it describes points aria-describedby at it.
const NOTE_GROUPS = ['featured', 'more', 'groups', 'moreGroups', 'formFigures', 'formGuests', 'formPresets']
const noteIds = Object.fromEntries(NOTE_GROUPS.map((g) => [g, `${uid}-note-${g}`]))
const noteHover = ref(null) // { group, key }
const noteChosen = reactive(Object.fromEntries(NOTE_GROUPS.map((g) => [g, null])))

function noteOn(group, key) {
  noteHover.value = { group, key }
}
// Only a mouse hovers: on a touch screen, changing the page on hover can swallow the tap.
function noteEnter(event, group, key) {
  if (event && event.pointerType === 'mouse') noteOn(group, key)
}
function noteLeave(group, key) {
  const h = noteHover.value
  if (h && h.group === group && h.key === key) noteHover.value = null
}
function noteChoose(group, key, chosen) {
  if (chosen) noteChosen[group] = key
  else if (noteChosen[group] === key) noteChosen[group] = null
}
const noteKeyOf = (group) => {
  const h = noteHover.value
  return h && h.group === group ? h.key : noteChosen[group]
}
const describedBy = (group, key) => (noteKeyOf(group) === key && notes.value[group] ? noteIds[group] : undefined)

function noteFor(key) {
  if (!key) return null
  const id = key.slice(2)
  if (key.startsWith('f:')) return figureLine(figureById(id), locale.value)
  if (key.startsWith('g:')) return guestLine(guestById(id), locale.value)
  if (key.startsWith('a:')) {
    const seated = stage.audience.find((a) => norm(a.name) === norm(id))
    const line = audienceLine({ name: id, description: seated ? seated.description : '' }, locale.value)
    return line && line.text ? line : null
  }
  return null
}
const notes = computed(() => Object.fromEntries(NOTE_GROUPS.map((g) => [g, noteFor(noteKeyOf(g))])))

const featured = featuredFigures()
const others = moreFigures()
const isMac = (() => {
  try {
    return /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '')
  } catch {
    return false
  }
})()

const currentStep = computed(() => STEPS[step.value] || null)
const stepId = computed(() => (currentStep.value ? currentStep.value.id : 'summary'))
const eraKey = computed(() => (ERA_IDS.includes(stage.era) ? stage.era : 'now'))

const progressText = computed(() =>
  step.value >= SUMMARY
    ? t('parthenon.builder.oracle.summary.heading')
    : t('parthenon.builder.oracle.progress', { n: STEPS[step.value].numeral, total: LAST_NUMERAL })
)
const progressAria = computed(() =>
  step.value >= SUMMARY
    ? t('parthenon.builder.oracle.summary.heading')
    : t('parthenon.builder.oracle.progressAria', { n: step.value + 1, total: STEPS.length })
)
const questionText = computed(() =>
  currentStep.value
    ? t(`parthenon.builder.oracle.steps.${currentStep.value.id}.question`)
    : t('parthenon.builder.oracle.summary.heading')
)
const voiceText = computed(() =>
  currentStep.value
    ? t(`parthenon.builder.oracle.steps.${currentStep.value.id}.voice`)
    : t('parthenon.builder.oracle.summary.voice')
)
// Enter moves on from a single line; in a text box, Enter starts a new line and Ctrl/⌘ Enter moves on.
const enterHint = computed(() => {
  const multi = stepId.value === 'words' || stepId.value === 'question'
  const keys = multi ? (isMac ? '⌘ Enter' : 'Ctrl Enter') : 'Enter'
  return t('parthenon.builder.oracle.enterHint', { keys })
})

const currentProblems = computed(() => (currentStep.value ? stepProblems(stage, currentStep.value.id) : []))
const shownProblems = computed(() => (attempted.value ? currentProblems.value : []))
const problemText = (p) => {
  const params = { ...(p.params || {}) }
  // A speaker named in a problem is named as the visitor reads them (苏格拉底, not Socrates).
  const sp = params.key ? stage.speakers.find((s) => s.key === params.key) : null
  if (sp) params.name = speakerLabel(sp, locale.value)
  return t(`parthenon.builder.oracle.problems.${p.code}`, params)
}
const wordsProblemKeys = computed(
  () => new Set(shownProblems.value.filter((p) => p.params && p.params.key).map((p) => p.params.key))
)

function announceStep(n) {
  if (n >= SUMMARY) announce(t('parthenon.builder.oracle.announceSummary'))
  else {
    announce(
      t('parthenon.builder.oracle.announceStep', {
        n: n + 1,
        total: STEPS.length,
        question: t(`parthenon.builder.oracle.steps.${STEPS[n].id}.question`),
      })
    )
  }
}

// Untouched template sentences never leave step Γ΄: the scroll gets words or nothing.
function clearUntouchedTemplates() {
  for (const sp of stage.speakers) if (isUntouchedTemplate(sp.words)) sp.words = ''
}

function arrive(n) {
  const id = STEPS[n] ? STEPS[n].id : 'summary'
  if (id === 'where') {
    if (!stage.setting.trim() && defaultSetting(stage.era, locale.value)) stage.setting = defaultSetting(stage.era, locale.value)
    else if (isOfferedSetting(stage.setting)) stage.setting = localSetting(stage.setting, locale.value)
  } else if (id === 'words') {
    for (const fill of templateFills(stage, locale.value)) {
      const sp = stage.speakers.find((s) => s.key === fill.key)
      if (sp) sp.words = fill.words
    }
  } else if (id === 'listeners') {
    if (!seated.value && !stage.audience.length) stage.audience.push(...defaultAudience(stage.era))
    seated.value = true
  } else if (id === 'question') {
    const offer = questionToOffer(stage, locale.value, lastOffered.value)
    if (offer != null) {
      stage.question = offer
      lastOffered.value = offer
    }
  }
}

function goTo(n, { focus = true } = {}) {
  const target = clampStep(n)
  if (stepId.value === 'words') clearUntouchedTemplates()
  undo.value = null
  attempted.value = false
  step.value = target
  arrive(target)
  focusOnEnter = focus
  announceStep(target)
}

function next() {
  if (props.disabled || step.value >= SUMMARY) return
  if (stepId.value === 'who') stage.format = fitFormat(stage.format, namedCount.value)
  if (currentProblems.value.length) {
    attempted.value = true
    return
  }
  goTo(step.value + 1)
}

function back() {
  if (step.value > 0) goTo(step.value - 1)
}

function onStepEntered() {
  if (!focusOnEnter) return
  focusOnEnter = false
  const heading = document.getElementById(walkIds.heading)
  if (!heading) return
  heading.focus({ preventScroll: true })
  // Keep the question in view: a long step may have left the page scrolled down.
  const top = heading.closest('.walk')?.getBoundingClientRect().top
  if (top != null && (top < 0 || top > window.innerHeight * 0.5)) {
    document.getElementById(walkIds.root)?.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  }
}

function onWalkKeydown(e) {
  if (e.key !== 'Enter' || e.isComposing || e.keyCode === 229 || e.defaultPrevented) return
  const el = e.target
  const tag = el && el.tagName
  if (tag === 'BUTTON' || tag === 'A' || tag === 'SUMMARY') return
  if (tag === 'TEXTAREA' && !(e.metaKey || e.ctrlKey)) return
  e.preventDefault()
  next()
}

// Α΄ who

function refit() {
  stage.format = fitFormat(stage.format, namedCount.value)
}

function walkRemoveSpeaker(sp) {
  const index = stage.speakers.findIndex((s) => s.key === sp.key)
  if (index < 0) return
  const list = namedSpeakers.value
  const at = list.findIndex((s) => s.key === sp.key)
  stage.speakers.splice(index, 1)
  openCards.delete(sp.key)
  const wasWordsOpen = wordsOpen.delete(sp.key)
  const wasMarked = marks.delete(`words:${sp.key}`)
  const name = speakerLabel(sp, locale.value) || displayName(sp)
  undo.value = { kind: 'speaker', item: sp, index, name, wasWordsOpen, wasMarked }
  announce(t('parthenon.builder.announceRemoved', { name }))
  refit()
  const nextSp = namedSpeakers.value[at] || namedSpeakers.value[at - 1]
  nextTick(() => {
    const target = nextSp ? document.getElementById(domId('wrm', nextSp.key)) : document.getElementById(walkIds.name)
    target?.focus()
  })
}

function toggleFigure(f, group = 'featured') {
  const existing = speakerForFigure(f)
  noteChoose(group, `f:${f.id}`, !existing)
  if (existing) return walkRemoveSpeaker(existing)
  if (speakersFull.value) return
  pushSpeaker(speakerFromFigure(f))
  refit()
}

function toggleGuest(g) {
  const existing = speakerForGuest(g)
  noteChoose('more', `g:${g.id}`, !existing)
  if (existing) return walkRemoveSpeaker(existing)
  if (speakersFull.value) return
  pushSpeaker(emptySpeaker({ name: g.name, role: g.role, ideas: g.ideas, voice: g.voice, guestId: g.id }))
  refit()
}

function addWrittenName() {
  const name = nameDraft.value.trim()
  if (!name || speakersFull.value) return
  const figure = figureForName(name)
  const guest = modernGuests.find((g) => norm(g.name) === norm(name) || norm(g.name).replace(/^the /, '') === norm(name))
  if (figure) {
    if (!speakerForFigure(figure)) pushSpeaker(speakerFromFigure(figure))
  } else if (guest) {
    if (!speakerForGuest(guest)) toggleGuest(guest)
  } else if (!stage.speakers.some((s) => norm(speakerName(s)) === norm(name))) {
    pushSpeaker(emptySpeaker({ name }))
  }
  nameDraft.value = ''
  refit()
  focusById(walkIds.name)
}

function onNameEnter(e) {
  if (e.isComposing || e.keyCode === 229) return
  if (!nameDraft.value.trim()) return // an empty line: Enter moves on
  e.preventDefault()
  addWrittenName()
}

// Β΄ where

const places = computed(() => placesFor(stage.era))

function chooseEra(id) {
  const before = stage.era
  if (before === id) return
  stage.era = id
  if (isOfferedSetting(stage.setting)) stage.setting = defaultSetting(id, locale.value)
  if (isDefaultAudience(stage.audience, before) && !isDefaultAudience(stage.audience, id)) {
    stage.audience.splice(0, stage.audience.length, ...defaultAudience(id))
  }
}

function choosePlace(place) {
  stage.setting = placeSetting(place, locale.value)
}

// Γ΄ words

function wordsHint(sp) {
  if (hasBlank(sp.words)) return t('parthenon.builder.oracle.words.blankHint')
  if (!knowsNothingOf(sp)) return t('parthenon.builder.oracle.words.figureHint', { name: speakerLabel(sp, locale.value) })
  return ''
}

// On the untouched template, the first blank is selected so typing replaces it.
function onWordsFocus(e) {
  const el = e.target
  if (!el || !isUntouchedTemplate(el.value)) return
  // A selection the visitor made by dragging or triple-clicking is theirs to keep.
  if (e.type === 'mouseup' && el.selectionStart !== el.selectionEnd) return
  const range = firstBlank(el.value)
  if (!range) return
  setTimeout(() => {
    if (document.activeElement === el && isUntouchedTemplate(el.value)) el.setSelectionRange(range[0], range[1])
  }, 0)
}

// Δ΄ listeners

const suggestionsNow = computed(() => audienceSuggestions(stage.era))
const featuredGroups = computed(() => suggestionsNow.value.filter((g) => g.featured))
const otherGroups = computed(() => suggestionsNow.value.filter((g) => !g.featured))
const isSeated = (name) => stage.audience.some((a) => norm(a.name) === norm(name))
// Groups on the steps that the Oracle did not offer for this age: the visitor's own.
const ownGroups = computed(() => {
  const offered = new Set(suggestionsNow.value.map((g) => norm(g.name)))
  return stage.audience.filter((a) => a.name.trim() && !offered.has(norm(a.name)))
})
const seatedCount = computed(() => stage.audience.filter((a) => a.name.trim()).length)

function toggleGroup(group, noteGroup = 'groups') {
  seated.value = true
  const index = stage.audience.findIndex((a) => norm(a.name) === norm(group.name))
  noteChoose(noteGroup, `a:${group.name}`, index < 0)
  if (index >= 0) {
    const member = stage.audience[index]
    stage.audience.splice(index, 1)
    marks.delete(`aud:${member.key}`)
    const name = audienceLabel(member.name, locale.value) || t('parthenon.builder.unnamedGroup')
    undo.value = { kind: 'listener', item: member, index, name, wasMarked: false }
    announce(t('parthenon.builder.announceLeft', { name }))
    return
  }
  if (crowdFull.value) return
  undo.value = null
  stage.audience.push(emptyAudienceMember({ name: group.name, description: group.description || '' }))
  announce(t('parthenon.builder.announceJoined', { name: audienceLabel(group.name, locale.value) }))
}

function addOwnGroup() {
  const name = groupDraft.value.trim()
  if (!name || crowdFull.value) return
  seated.value = true
  const known = audienceSuggestions(stage.era).find((g) => norm(g.name) === norm(name) || norm(g.zh.name) === norm(name))
  if (!isSeated(known ? known.name : name)) {
    stage.audience.push(emptyAudienceMember(known ? { name: known.name, description: known.description } : { name }))
    announce(t('parthenon.builder.announceJoined', { name: audienceLabel(known ? known.name : name, locale.value) }))
  }
  groupDraft.value = ''
  focusById(walkIds.group)
}

function onGroupEnter(e) {
  if (e.isComposing || e.keyCode === 229) return
  if (!groupDraft.value.trim()) return
  e.preventDefault()
  addOwnGroup()
}

function walkUndo() {
  const u = undo.value
  undoRemove()
  if (u && u.kind === 'speaker') refit()
  // undoRemove focuses the full form's fields; here, the chip or token that came back.
  nextTick(() => {
    if (!u) return
    const el = u.kind === 'speaker' ? document.getElementById(domId('wrm', u.item.key)) : document.getElementById(walkIds.group)
    el?.focus()
  })
}

// Ε΄ question

const quarrels = computed(() => quarrelsFor(stage.era))
const questionFrom = computed(() => questionSource(stage, locale.value))

function useQuarrel(q) {
  const text = quarrelQuestion(stage, q, locale.value)
  stage.question = text
  lastOffered.value = text
  unmark('question')
}

function useOracleQuestion() {
  const text = suggestQuestionFor(stage, locale.value)
  stage.question = text
  lastOffered.value = text
  unmark('question')
  focusById(walkIds.question)
}

// The stage, as a scroll

const clip = (text, max) => {
  const s = str(text).replace(/\s+/g, ' ').trim()
  return s.length > max ? `${s.slice(0, max - 1).replace(/\s+\S*$/, '')}…` : s
}

const namesHere = computed(() => namedSpeakers.value.map((s) => speakerLabel(s, locale.value)))

const summaryTitle = computed(() => {
  if (stage.title.trim()) return stage.title.trim()
  if (!String(locale.value).startsWith('zh')) return preview.value.title
  const names = joinOracleNames(namesHere.value.slice(0, 3), locale.value)
  const format = t(`parthenon.builder.oracle.formatNoun.${stage.format}`)
  return names ? t('parthenon.builder.oracle.titleFor', { names, format }) : format
})

// '399 BC · Athens, 399 BC, in the Agora' says the year twice; say it once.
const whereText = (era, place) => {
  if (!place) return era
  const year = (era.match(/\d{3,4}/) || [])[0]
  return year && place.includes(year) ? place : `${era} · ${place}`
}

const summaryRows = computed(() => {
  const L = (k) => t(`parthenon.builder.oracle.summary.${k}`)
  const listeners = stage.audience.filter((a) => a.name.trim()).map((a) => audienceLabel(a.name, locale.value))
  const era = t(`parthenon.builder.oracle.eras.${eraKey.value}.year`)
  const place = localSetting(stage.setting, locale.value)
  return [
    { id: 'who', step: 0, label: L('who'), text: joinOracleNames(namesHere.value, locale.value) },
    { id: 'where', step: 1, label: L('where'), text: whereText(era, place) },
    {
      id: 'words',
      step: 2,
      label: L('words'),
      words: namedSpeakers.value.map((s) => ({ key: s.key, name: speakerLabel(s, locale.value), text: clip(s.words, 240) })),
    },
    { id: 'listeners', step: 3, label: L('listeners'), text: listeners.length ? joinOracleNames(listeners, locale.value) : L('cityAtLarge') },
    { id: 'question', step: 4, label: L('question'), text: stage.question.trim() },
  ]
})

// Everything still unanswered, each with the step that answers it.
const summaryProblems = computed(() => {
  const list = allProblems(stage).map((p) => ({ text: problemText(p), step: p.step }))
  if (!list.length) {
    // Anything the full form still objects to (a repeated name, the Oracle still drafting).
    for (const text of takeProblems.value) list.push({ text, step: null })
  }
  return list
})

const canSpeak = computed(() => canTake.value && summaryProblems.value.length === 0)

function speak() {
  if (!canSpeak.value) return
  takeStage()
}

function openForm() {
  if (stepId.value === 'words') clearUntouchedTemplates()
  attempted.value = false
  mode.value = 'form'
  announce(t('parthenon.builder.oracle.announceForm'))
  nextTick(() => {
    const btn = document.getElementById(walkIds.returnBtn)
    if (!btn) return
    btn.focus({ preventScroll: true })
    btn.scrollIntoView({ behavior: prefersReducedMotion() ? 'auto' : 'smooth', block: 'start' })
  })
}

function returnToWalk() {
  mode.value = 'walk'
  // The form may have emptied an earlier answer; the Oracle asks that one again.
  const target = Math.min(step.value, firstOpenStep(stage))
  attempted.value = false
  step.value = target
  arrive(target)
  announce(t('parthenon.builder.oracle.announceWalk'))
  // The walk is created afresh (no enter transition on first render), so focus it here.
  nextTick(() => {
    focusOnEnter = true
    onStepEntered()
  })
}

function resetWalk() {
  step.value = 0
  seated.value = false
  lastOffered.value = ''
  attempted.value = false
  nameDraft.value = ''
  groupDraft.value = ''
}

// ---------------------------------------------------------------------------
// Start over, and what the page can ask of the builder

function clearTransient() {
  oracleToken += 1
  clearTimeout(slowTimer)
  oracle.pending = false
  oracle.slow = false
  oracle.error = ''
  oracle.result = null
  undo.value = null
  taken.value = ''
}

function startOver() {
  let ok = true
  try {
    ok = window.confirm(t('parthenon.builder.confirmStartOver'))
  } catch {
    ok = true
  }
  if (!ok) return
  clearTransient()
  replaceStage(emptyStage())
  resetUiFor(stage)
  resetWalk()
  clearTimeout(saveTimer)
  saveTimer = null
  try {
    window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Ignore: nothing was stored.
  }
  draftState.value = 'none'
  announce(t('parthenon.builder.announceCleared'))
}

/** Replace the whole stage (for example with an arrival to remix). */
function loadStage(next) {
  clearTransient()
  replaceStage(normalizeStage({ ...emptyStage(), ...(next && typeof next === 'object' ? next : {}) }))
  resetUiFor(stage)
  resetWalk()
  seated.value = stage.audience.length > 0
  // A whole stage arrives answered: the Oracle opens on the first question it still needs.
  step.value = firstOpenStep(stage)
}

/** Put a roster figure on the stage (or reveal them if already there). */
function summon(figureId) {
  const figure = figureById(figureId)
  if (!figure) return false
  const existing = speakerForFigure(figure)
  if (mode.value === 'walk') {
    if (!existing) {
      if (speakersFull.value) return false
      pushSpeaker(speakerFromFigure(figure))
      refit()
    }
    if (step.value !== 0) goTo(0)
    return true
  }
  if (existing) revealSpeaker(existing)
  else if (!speakersFull.value) {
    const sp = speakerFromFigure(figure)
    pushSpeaker(sp)
    focusById(domId('name', sp.key), { scroll: true })
  } else return false
  return true
}

defineExpose({ loadStage, summon })

const onPageHide = () => flushSave()

onMounted(() => {
  window.addEventListener('pagehide', onPageHide)
})

onBeforeUnmount(() => {
  alive = false
  window.removeEventListener('pagehide', onPageHide)
  clearTimeout(slowTimer)
  flushSave()
})
</script>

<style scoped>
.stage-builder {
  /* Control boundaries need 3:1 against the page (WCAG 1.4.11); --p-line is for dividers. */
  --sb-control-border: var(--p-control-border, color-mix(in srgb, var(--p-ink) 40%, transparent));

  width: 100%;
  max-width: 900px;
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
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

.shell {
  min-width: 0;
  margin: 0;
  padding: 0;
  border: 0;
}

.stage-builder button:focus-visible,
.stage-builder summary:focus-visible {
  outline: 2px solid var(--p-terracotta);
  outline-offset: 2px;
}

/* Parts, each under a Greek numeral */
.part {
  padding: 28px 0;
  border-top: 1px solid var(--p-line);
}

.part:first-child {
  padding-top: 0;
  border-top: none;
}

.part-label {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-bottom: 6px;
  font-family: var(--p-font-inscription);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--p-ink-2);
}

.part-numeral {
  min-width: 30px;
  font-family: var(--p-font-display);
  font-size: 22px;
  font-weight: 500;
  letter-spacing: 0;
  line-height: 1;
  color: var(--p-terracotta);
}

.part-help {
  max-width: 640px;
  margin-bottom: 16px;
  font-size: 15px;
  line-height: 1.55;
  color: var(--p-ink-3);
}

/* Fields */
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 14px;
  min-width: 0;
}

.field-label {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.field-optional {
  font-family: var(--p-font-body);
  font-size: 12px;
  font-style: italic;
  font-weight: 400;
  letter-spacing: 0;
  text-transform: none;
  color: var(--p-ink-4);
}

.field-help {
  font-size: 13px;
  line-height: 1.5;
  color: var(--p-ink-4);
}

.input {
  width: 100%;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--sb-control-border);
  border-radius: 0;
  background: var(--p-surface);
  font-family: var(--p-font-body);
  font-size: 15px;
  line-height: 1.55;
  color: var(--p-ink);
}

textarea.input {
  display: block;
  resize: vertical;
}

.input::placeholder {
  color: var(--p-ink-4);
  font-style: italic;
}

.input:focus {
  outline: none;
  border-color: var(--p-terracotta);
  box-shadow: 0 0 0 3px var(--p-terracotta-tint);
}

.input:disabled {
  background: var(--p-surface-2);
  color: var(--p-ink-3);
}

.question-input {
  padding: 14px 16px;
  font-size: 16px;
  line-height: 1.6;
}

/* Α΄ Formats: cards with radio semantics */
.format-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 10px;
}

.format-option {
  display: block;
  cursor: pointer;
}

.format-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 100%;
  padding: 14px 14px 12px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
}

.format-option:hover .format-card {
  border-color: var(--p-line-strong);
}

.format-option input:checked + .format-card {
  border-color: var(--p-terracotta);
  background: linear-gradient(180deg, var(--p-surface), var(--p-terracotta-tint));
  box-shadow: 0 0 0 1px var(--p-terracotta) inset;
}

.format-option input:focus-visible + .format-card {
  outline: 2px solid var(--p-terracotta);
  outline-offset: 2px;
}

.format-glyph {
  width: 48px;
  height: 28px;
  margin-bottom: 4px;
  fill: currentColor;
  stroke: currentColor;
  stroke-width: 1.3;
  stroke-linecap: round;
  stroke-linejoin: round;
  color: var(--p-ink-4);
}

.format-glyph path {
  fill: none;
}

.format-glyph circle {
  stroke: none;
}

.format-option input:checked + .format-card .format-glyph {
  color: var(--p-terracotta);
}

.format-name {
  font-family: var(--p-font-display);
  font-size: 21px;
  font-weight: 600;
  line-height: 1.1;
  color: var(--p-ink);
}

.format-blurb {
  flex: 1;
  font-size: 13px;
  line-height: 1.45;
  color: var(--p-ink-3);
}

.format-voices {
  margin-top: 6px;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-terracotta-deep);
}

/* Β΄ Eras: pills */
.pill-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.pill-option {
  cursor: pointer;
}

.pill {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  padding: 8px 14px;
  border: 1px solid var(--sb-control-border);
  background: var(--p-surface);
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.pill-option:hover .pill {
  border-color: var(--p-ink-3);
  color: var(--p-ink);
}

.pill-option input:checked + .pill {
  background: var(--p-ink);
  border-color: var(--p-ink);
  color: var(--p-surface);
}

.pill-option input:focus-visible + .pill {
  outline: 2px solid var(--p-terracotta);
  outline-offset: 2px;
}

/* Chips: sparks, roster, presets */
.chip-group {
  margin-top: 18px;
}

.chip-group-label {
  margin-bottom: 8px;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  min-height: 36px;
  padding: 4px 12px 4px 4px;
  border: 1px solid var(--sb-control-border);
  background: var(--p-surface);
  font-family: var(--p-font-body);
  font-size: 14px;
  line-height: 1.3;
  color: var(--p-ink-2);
  text-align: left;
  cursor: pointer;
}

.chip:hover:not(:disabled) {
  border-color: var(--p-terracotta);
  color: var(--p-ink);
}

.chip:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.chip.spark,
.chip.plain {
  padding: 6px 12px;
}

.chip.spark.chosen,
.chip.on-stage {
  border-color: var(--p-terracotta);
  background: var(--p-terracotta-tint);
}

.chip-name {
  min-width: 0;
  overflow-wrap: anywhere;
}

.chip-coin {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: var(--p-terracotta);
  font-family: var(--p-font-display);
  font-size: 16px;
  font-weight: 600;
  line-height: 1;
  color: var(--p-surface);
}

.chip-coin.modern {
  background: var(--p-surface-3);
  font-family: var(--p-font-inscription);
  font-size: 12px;
  color: var(--p-ink);
}

.chip.on-stage .chip-coin {
  background: var(--p-ink);
  color: var(--p-surface);
}

.chip-state {
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--p-terracotta-deep);
}

.chip-plus {
  font-size: 15px;
  line-height: 1;
  color: var(--p-terracotta);
}

/* Δ΄ Speakers */
.range-line {
  margin-bottom: 14px;
  font-size: 14px;
  color: var(--p-ink-3);
}

.range-line.warn {
  padding: 8px 12px;
  border-left: 2px solid var(--p-ochre);
  background: var(--p-ochre-tint);
  color: var(--p-ink-2);
}

.speaker-list,
.crowd-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.speaker-editor {
  min-width: 0;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
}

.speaker-editor.open {
  border-color: var(--p-line-strong);
}

.speaker-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px 8px 8px;
}

.speaker-toggle {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  padding: 4px;
  border: none;
  background: none;
  font: inherit;
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.coin {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--p-terracotta);
  box-shadow: 0 0 0 2px var(--p-surface), 0 0 0 3px var(--p-terracotta);
}

.coin span {
  font-family: var(--p-font-display);
  font-size: 22px;
  font-weight: 600;
  line-height: 1;
  color: var(--p-surface);
}

.coin.modern {
  background: var(--p-surface-3);
  box-shadow: 0 0 0 2px var(--p-surface), 0 0 0 3px var(--p-ink-3);
}

.coin.modern span {
  font-family: var(--p-font-inscription);
  font-size: 16px;
  color: var(--p-ink);
}

.coin.own {
  background: var(--p-surface-2);
  box-shadow: 0 0 0 2px var(--p-surface), 0 0 0 3px var(--p-line-strong);
}

.coin.own span {
  color: var(--p-ink-3);
}

.speaker-editor.open .coin.ancient {
  background: var(--p-ink);
}

.speaker-editor.open .coin.ancient span {
  color: var(--p-surface);
}

.speaker-head-text {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.speaker-head-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--p-font-inscription);
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--p-ink);
}

.speaker-head-greek {
  font-size: 12px;
  letter-spacing: 0.12em;
  color: var(--p-ink-4);
}

.speaker-head-role {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--p-ink-3);
}

.speaker-head-state {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 3px;
}

.word-count {
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  white-space: nowrap;
  color: var(--p-ink-4);
}

.chevron {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  margin: 0 4px 4px;
  border-right: 1.5px solid var(--p-ink-3);
  border-bottom: 1.5px solid var(--p-ink-3);
  transform: rotate(45deg);
  transition: transform 0.2s;
}

[aria-expanded='true'] > .chevron {
  margin: 4px 4px 0;
  transform: rotate(-135deg);
}

.speaker-tools {
  flex-shrink: 0;
  display: flex;
  gap: 4px;
}

.icon-btn {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border: 1px solid var(--sb-control-border);
  background: var(--p-surface);
  font-size: 16px;
  line-height: 1;
  color: var(--p-ink-3);
  cursor: pointer;
}

.icon-btn:hover:not(:disabled) {
  border-color: var(--p-ink-3);
  color: var(--p-ink);
}

.icon-btn.remove {
  font-size: 20px;
}

.icon-btn.remove:hover:not(:disabled) {
  border-color: var(--p-error);
  color: var(--p-error);
}

.icon-btn:disabled {
  opacity: 0.35;
  cursor: default;
}

.speaker-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 0 14px;
  padding: 2px 16px 16px;
  border-top: 1px solid var(--p-line);
}

.speaker-body .field.wide {
  grid-column: 1 / -1;
}

.words-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 42px;
  padding: 8px 12px;
  border: 1px dashed var(--p-line-strong);
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.words-toggle:hover {
  border-color: var(--p-terracotta);
  background: var(--p-surface-2);
}

.words-toggle[aria-expanded='true'] {
  border-style: solid;
}

.words-toggle-label {
  flex: 1;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-ink-2);
}

.words-panel {
  margin-top: -1px;
}

.words-input {
  font-family: var(--p-font-display);
  font-size: 18px;
  line-height: 1.5;
}

.empty-line {
  padding: 16px;
  border: 1px dashed var(--p-line-strong);
  font-size: 14px;
  font-style: italic;
  color: var(--p-ink-4);
}

.empty-line.small {
  padding: 0;
  border: none;
  font-size: 13px;
}

.undo-line {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: 10px;
  font-size: 14px;
  color: var(--p-ink-3);
}

.add-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 14px;
  margin-top: 12px;
}

.add-btn,
.text-btn {
  padding: 4px 0;
  border: none;
  background: none;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--p-terracotta);
  cursor: pointer;
}

.add-btn {
  padding: 9px 14px;
  border: 1px dashed var(--p-terracotta);
}

.add-btn:hover:not(:disabled) {
  background: var(--p-terracotta-tint);
}

.text-btn:hover:not(:disabled) {
  color: var(--p-terracotta-deep);
  text-decoration: underline;
  text-underline-offset: 3px;
}

.add-btn:disabled,
.text-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.text-btn.quiet {
  color: var(--p-ink-4);
}

.text-btn.quiet:hover:not(:disabled) {
  color: var(--p-error);
}

.full-note {
  font-size: 13px;
  font-style: italic;
  color: var(--p-ink-4);
}

/* Ε΄ Crowd */
.crowd-heads {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr) 32px;
  gap: 8px;
  padding: 0 9px 6px;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-ink-4);
}

.crowd-list {
  gap: 8px;
}

.crowd-row {
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(0, 3fr) auto;
  align-items: start;
  gap: 8px;
  padding: 8px;
  background: var(--p-surface);
  border: 1px solid var(--p-line);
}

.crowd-row.drafted {
  border-left: 2px solid var(--p-ink-3);
}

.crowd-name {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  min-width: 0;
}

.crowd-desc {
  min-width: 0;
}

.crowd-row .input {
  font-size: 14px;
}

/* Oracle marks: what the machine drafted, until you touch it */
.oracle-tag {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border: 1px solid var(--p-terracotta);
  background: var(--p-surface-3);
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-ink-3);
  white-space: nowrap;
}

/* The altar: the Oracle, then the stage */
.altar {
  margin-top: 4px;
  padding: 22px clamp(16px, 3vw, 26px) 16px;
  background: var(--p-surface-2);
  border: 1px solid var(--p-line-strong);
}

.oracle {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px 18px;
}

.tripod {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  overflow: visible;
  fill: none;
  stroke: var(--p-ink-3);
  stroke-width: 1.3;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.tripod-vapour {
  stroke-width: 0.9;
  opacity: 0.7;
}

.oracle-copy {
  flex: 1 1 260px;
  min-width: 0;
}

.oracle-eyebrow {
  margin-bottom: 4px;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.oracle-desc {
  font-size: 14px;
  line-height: 1.55;
  color: var(--p-ink-3);
}

.oracle-btn {
  flex-shrink: 0;
  padding: 12px 18px;
  border: 1px solid var(--p-ink);
  background: transparent;
  font-family: var(--p-font-inscription);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-ink);
  cursor: pointer;
}

.oracle-btn:hover:not(:disabled) {
  background: var(--p-ink);
  color: var(--p-surface);
}

.oracle-btn:disabled {
  border-color: var(--p-line-strong);
  color: var(--p-ink-4);
  cursor: not-allowed;
}

.oracle-why {
  margin-top: 10px;
  font-size: 13px;
  font-style: italic;
  color: var(--p-ink-4);
}

.oracle-status:not(:empty) {
  margin-top: 14px;
  padding: 12px 14px;
  border-left: 2px solid var(--p-ink-3);
  background: var(--p-surface-3);
}

.vapour,
.oracle-spoke {
  font-family: var(--p-font-display);
  font-size: 19px;
  font-style: italic;
  line-height: 1.35;
  color: var(--p-ink-2);
}

.vapour {
  animation: vapour 3.2s ease-in-out infinite;
}

@keyframes vapour {
  0%,
  100% {
    opacity: 0.55;
  }
  50% {
    opacity: 1;
  }
}

.oracle-sub {
  margin-top: 4px;
  font-size: 13px;
  color: var(--p-ink-3);
}

.oracle-status .text-btn {
  margin-top: 6px;
}

.oracle-error {
  margin-top: 14px;
  padding: 12px 14px;
  border-left: 2px solid var(--p-error);
  background: var(--p-error-tint);
  font-size: 14px;
  color: var(--p-ink-2);
}

.take {
  margin-top: 22px;
  padding-top: 20px;
  border-top: 1px solid var(--p-line-strong);
}

.problems,
.hints {
  font-size: 14px;
  line-height: 1.5;
}

.problems {
  margin-bottom: 14px;
  color: var(--p-ink-2);
}

.problems-label,
.hints-label {
  margin-bottom: 6px;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-terracotta-deep);
}

.hints-label {
  color: var(--p-ink-4);
}

.problems ul,
.hints ul {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.problems li,
.hints li {
  position: relative;
  padding-left: 16px;
}

.problems li::before,
.hints li::before {
  content: '';
  position: absolute;
  left: 2px;
  top: 0.62em;
  width: 5px;
  height: 5px;
  background: var(--p-terracotta);
  transform: rotate(45deg);
}

.hints {
  margin-top: 16px;
  font-size: 13px;
  color: var(--p-ink-4);
}

.hints li::before {
  background: var(--p-line-strong);
}

.begin {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 18px 22px;
  border: none;
  background: var(--p-terracotta);
  color: var(--p-surface);
  font-family: var(--p-font-inscription);
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  cursor: pointer;
  transition: transform 0.2s;
}

.begin:hover:not(:disabled) {
  background: var(--p-terracotta-deep);
}

.begin:active:not(:disabled) {
  transform: translateY(1px);
}

/* Disabled reads at night: stone on stone, the reason beside it, never ink on a dark line. */
.begin:disabled {
  background: var(--p-surface-3);
  color: var(--p-ink-3);
  box-shadow: inset 0 0 0 1px var(--p-line);
  cursor: not-allowed;
}

.begin-arrow {
  font-family: var(--p-font-body);
  font-size: 22px;
}

.taken-line {
  margin-top: 10px;
  font-size: 14px;
  color: var(--p-ink-2);
}

/* Preview of the seed scroll */
.preview {
  /* The ring round the scroll: the gold of the stone around it, since
     .p-paper turns the gold on the sheet itself to bronze. */
  --sheet-ring: var(--p-gold);
  margin-top: 20px;
}

.preview summary {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--p-ink-3);
  cursor: pointer;
  list-style: none;
}

.preview summary::-webkit-details-marker {
  display: none;
}

.preview summary::before {
  content: '❦';
  color: var(--p-terracotta);
  letter-spacing: 0;
}

.preview summary:hover {
  color: var(--p-ink);
}

/* The scroll is parchment held up in the dark: .p-paper turns the tokens to
   ink on stone, so nothing here names a colour of its own. */
.scroll-sheet {
  max-height: 460px;
  margin-top: 12px;
  overflow-y: auto;
  padding: 24px 28px;
  background-color: var(--p-surface-2);
  background-image: var(--p-marble-texture);
  box-shadow: var(--p-shadow-2), inset 0 0 60px rgba(160, 110, 50, 0.14);
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.7;
  color: var(--p-ink-2);
  overflow-wrap: anywhere;
}

.scroll-sheet:focus-visible {
  outline: 2px solid var(--sheet-ring, var(--p-gold));
  outline-offset: 4px;
}

.scroll-sheet :deep(h3) {
  margin-bottom: 10px;
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 600;
  line-height: 1.15;
  color: var(--p-ink);
}

.scroll-sheet :deep(h4) {
  margin: 22px 0 8px;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 600;
  color: var(--p-terracotta);
}

.scroll-sheet :deep(p) {
  margin-bottom: 12px;
}

.scroll-sheet :deep(ul) {
  margin: 0 0 12px 18px;
}

.scroll-sheet :deep(li) {
  margin-bottom: 4px;
}

.scroll-sheet :deep(strong) {
  color: var(--p-ink);
}

.scroll-note {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: 4px 10px;
  margin-top: 10px;
  font-size: 13px;
  color: var(--p-ink-4);
}

.scroll-note code {
  font-family: var(--p-font-mono);
  font-size: 12px;
  color: var(--p-ink-3);
  overflow-wrap: anywhere;
}

.altar-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 18px;
  padding-top: 12px;
  border-top: 1px solid var(--p-line);
}

.draft-note {
  font-size: 13px;
  font-style: italic;
  color: var(--p-ink-4);
}

/* When the page is busy, everything waits */
.shell:disabled .format-option,
.shell:disabled .pill-option {
  cursor: not-allowed;
  opacity: 0.6;
}

@media (max-width: 640px) {
  .speaker-body {
    grid-template-columns: minmax(0, 1fr);
    padding: 2px 12px 14px;
  }

  .speaker-head {
    flex-wrap: wrap;
  }

  .speaker-toggle {
    flex-basis: 100%;
  }

  .speaker-tools {
    width: 100%;
    justify-content: flex-end;
  }

  .crowd-heads {
    display: none;
  }

  .crowd-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .crowd-desc {
    grid-column: 1 / -1;
    grid-row: 2;
  }

  .crowd-desc textarea {
    min-height: 92px;
  }

  .scroll-sheet {
    padding: 18px;
  }

  .begin {
    padding: 16px 18px;
    font-size: 14px;
  }
}

/* Chinese labels: Cinzel carries no hanzi, and wide tracking pulls characters apart. */
.chip-group-label:lang(zh),
.field-label:lang(zh),
.part-label:lang(zh),
.oracle-tag:lang(zh),
.text-btn:lang(zh),
.walk-problems-label:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.06em;
}

/* ---------------------------------------------------------------------------
   The Oracle at the bema. She speaks from her alcove on the right, a dim crop
   of the bema's stone with the tripod alight; the visitor answers on the left,
   one question per screen. On a phone her alcove becomes the band above. */

.stage-builder.walking {
  max-width: none;
}

.walk {
  position: relative;
  padding: 4px 0 12px;
  scroll-margin-top: 88px;
}

.walk-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 0.6fr);
  grid-template-areas: 'answers pythia';
  column-gap: clamp(32px, 4.5vw, 72px);
  align-items: start;
}

.walk-answers {
  grid-area: answers;
  min-width: 0;
}

/* Her alcove */
.walk-pythia {
  grid-area: pythia;
  position: sticky;
  top: calc(var(--p-header-h, 64px) + 28px);
  isolation: isolate;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  min-height: min(600px, calc(100vh - var(--p-header-h, 64px) - 64px));
  border: 1px solid color-mix(in srgb, var(--p-gold) 24%, transparent);
  background: #07090d;
  box-shadow: var(--p-shadow-2);
}

/* A hairline of gold along the top, like the lip of a bronze bowl */
.walk-pythia::before {
  content: '';
  position: absolute;
  inset: 0 18% auto;
  height: 1px;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--p-gold) 70%, transparent), transparent);
}

.walk-pythia-plate {
  position: absolute;
  inset: 0;
  z-index: -1;
  pointer-events: none;
}

.walk-pythia-img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  /* The rock-cut face of the bema and the platform before it, not the Acropolis
     already shown above: the Oracle's own stone. */
  object-position: 30% 50%;
  opacity: 0.46;
  filter: saturate(0.72) contrast(1.06);
  transform: scale(1.08);
  transform-origin: 30% 60%;
}

.walk-pythia-shade {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(180deg, rgba(7, 9, 13, 0.62) 0%, rgba(7, 9, 13, 0.18) 30%, rgba(7, 9, 13, 0.5) 54%, rgba(7, 9, 13, 0.92) 76%, #07090d 100%),
    linear-gradient(90deg, rgba(7, 9, 13, 0.5), rgba(7, 9, 13, 0) 28%, rgba(7, 9, 13, 0) 72%, rgba(7, 9, 13, 0.5));
}

/* The fire in the bowl of the tripod */
.walk-pythia-glow {
  position: absolute;
  left: 50%;
  top: 24%;
  width: 360px;
  height: 320px;
  transform: translate(-50%, -50%);
  background: radial-gradient(closest-side, rgba(240, 182, 96, 0.3), rgba(240, 182, 96, 0.1) 52%, rgba(240, 182, 96, 0) 100%);
  animation: walk-ember 7s ease-in-out infinite;
  transition: opacity 0.8s ease, transform 0.8s ease;
}

.walk-grid.telos .walk-pythia-glow {
  transform: translate(-50%, -50%) scale(1.22);
}

@keyframes walk-ember {
  0%,
  100% {
    opacity: 0.78;
  }
  38% {
    opacity: 1;
  }
  64% {
    opacity: 0.86;
  }
}

.walk-pythia-body {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  padding: clamp(30px, 3.2vw, 44px) clamp(26px, 3vw, 44px) clamp(32px, 3.2vw, 44px);
}

.walk-pythia-sign {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
  text-align: center;
}

.walk-tripod {
  flex-shrink: 0;
  width: 112px;
  height: 112px;
  overflow: visible;
  fill: none;
  stroke: var(--p-gold);
  stroke-width: 0.72;
  stroke-linecap: round;
  stroke-linejoin: round;
  filter: drop-shadow(0 0 14px rgba(240, 182, 96, 0.45));
}

.walk-tripod.small {
  width: 20px;
  height: 20px;
  stroke: currentColor;
  stroke-width: 1.9;
  filter: none;
}

/* The vapour from the cleft: each thread (pathLength 1) rises out of the rock
   as a wisp, climbs toward the bowl and thins away; the two take turns. */
.walk-vapour {
  stroke-width: 0.55;
  stroke-dasharray: 0.7 1;
  stroke-dashoffset: 0.7;
  opacity: 0;
  animation: walk-vapour 6.4s cubic-bezier(0.4, 0.1, 0.6, 0.9) infinite;
}

.walk-vapour.late {
  stroke-width: 0.45;
  animation-delay: -3.2s;
}

@keyframes walk-vapour {
  0% {
    stroke-dashoffset: 0.7;
    opacity: 0;
  }
  16% {
    opacity: 0.95;
  }
  68% {
    opacity: 0.8;
  }
  100% {
    stroke-dashoffset: -1;
    opacity: 0;
  }
}

.walk-oracle {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  margin: 0;
}

.walk-delphi {
  font-family: var(--p-font-inscription);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.42em;
  margin-right: -0.42em;
  color: var(--p-gold);
}

.walk-oracle-name {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.walk-oracle-name:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.08em;
}

/* What she asks, in her own voice */
.walk-speech {
  margin-top: auto;
  padding-top: 36px;
}

.walk-speech::before {
  content: '';
  display: block;
  width: 44px;
  height: 1px;
  margin-bottom: 18px;
  background: var(--p-gold);
  opacity: 0.7;
}

.walk-question {
  margin: 0;
  font-family: var(--p-font-display);
  font-size: clamp(1.75rem, 2.4vw, 2.25rem);
  font-style: italic;
  font-weight: 500;
  line-height: 1.12;
  text-wrap: balance;
  color: var(--p-ink);
}

.walk-question:focus,
.walk-question:focus-visible {
  /* Focus lands here to carry the reader to the new question; it is not a control. */
  outline: none;
}

.walk-voice {
  max-width: 34ch;
  margin: 14px 0 0;
  font-family: var(--p-font-display);
  font-size: 1.3rem;
  font-style: italic;
  line-height: 1.45;
  color: var(--p-ink-2);
}

/* Her words form out of the vapour: a short blur, never a slide */
.speech-enter-active,
.speech-leave-active {
  transition: opacity 0.42s ease, filter 0.42s ease, transform 0.42s ease;
}

.speech-enter-from {
  opacity: 0;
  filter: blur(6px);
  transform: translateY(6px);
}

.speech-leave-to {
  opacity: 0;
  filter: blur(4px);
}

/* The answers: where you are, then the question's controls */
.walk-head {
  display: flex;
  align-items: flex-end;
  gap: 18px;
}

.walk-marks {
  flex: 1 1 auto;
  display: flex;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.walk-marks li {
  flex: 1 1 0;
  padding-top: 8px;
  border-top: 2px solid var(--p-line);
  font-family: var(--p-font-display);
  font-size: var(--t-sm);
  color: var(--p-ink-4);
}

.walk-marks li.done {
  border-top-color: color-mix(in srgb, var(--p-gold) 50%, transparent);
  color: var(--p-ink-3);
}

.walk-marks li.now {
  border-top-color: var(--p-gold);
  color: var(--p-gold);
}

.walk-progress {
  flex-shrink: 0;
  margin: 0;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  line-height: 1;
  letter-spacing: 0.04em;
  color: var(--p-ink-3);
}

.walk-progress.telos {
  font-family: var(--p-font-inscription);
  font-size: var(--t-sm);
  letter-spacing: 0.3em;
  color: var(--p-gold);
}

.walk-step {
  padding: clamp(24px, 3vw, 34px) 0 4px;
}

.walk-body {
  margin-top: 0;
}

.walk .chip-group-label {
  margin-bottom: 10px;
}

.walk .chip-group {
  margin-top: 20px;
}

.walk-chip {
  min-height: 44px;
}

.walk-chip.on-stage {
  border-color: var(--p-gold);
  background: var(--p-terracotta-tint);
  color: var(--p-ink);
}

.walk-chip .chip-coin:not(.modern) {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--p-gold) 55%, transparent);
  background: var(--p-surface-3);
  color: var(--p-gold);
}

.walk-chip.on-stage .chip-coin,
.walk-chip.on-stage .chip-coin:not(.modern) {
  box-shadow: none;
  background: var(--p-gold);
  color: #1f1a16;
}

.walk-chip.on-stage .chip-plus {
  color: var(--p-gold);
}

/* The Oracle's line about a chip: who they were, or what a group stands to lose */
.chip-note {
  min-height: 3em;
  max-width: 66ch;
  margin: 12px 0 0;
  font-family: var(--p-font-serif);
  font-size: 15px;
  line-height: 1.5;
  color: var(--p-ink-2);
}

.chip-note.idle {
  font-style: italic;
  color: var(--p-ink-4);
}

.chip-note-name {
  margin-right: 8px;
  font-family: var(--p-font-display);
  font-size: 1.15rem;
  font-weight: 600;
  color: var(--p-gold);
}

.chip-note-when {
  margin-right: 8px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--p-ink-3);
}

.chip-note-when:lang(zh),
.chip-note-name:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0;
}

.walk-more,
.walk-text-btn,
.walk-undo {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 44px;
}

.walk-more {
  margin-top: 2px;
}

.walk-more-mark {
  width: 14px;
  font-family: var(--p-font-body);
  font-size: 16px;
  text-align: center;
}

.walk-more-body {
  margin-top: 4px;
}

.walk-more-body > .chip-note {
  min-height: 0;
}

.walk-sub-label {
  margin-top: 16px;
}

.walk-write {
  margin-top: 16px;
}

.walk-inline {
  display: flex;
  gap: 8px;
}

.walk-inline .input {
  flex: 1 1 auto;
  min-height: 48px;
}

.walk-add {
  flex-shrink: 0;
}

.walk-floor {
  margin-top: 22px;
}

.walk-tokens {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.walk-token {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  max-width: 100%;
  padding-left: 8px;
  border: 1px solid var(--p-gold);
  background: var(--p-terracotta-tint);
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  line-height: 1.2;
  color: var(--p-ink);
}

.walk-token .chip-coin {
  background: var(--p-gold);
  color: #1f1a16;
}

.walk-token-name {
  min-width: 0;
  overflow-wrap: anywhere;
}

.walk-token-x {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  border: none;
  background: none;
  font-family: var(--p-font-body);
  font-size: 20px;
  color: var(--p-ink-3);
  cursor: pointer;
}

.walk-token-x:hover {
  color: var(--p-gold);
}

.walk-note {
  margin-top: 10px;
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-3);
}

/* Β΄ the ages */
.walk-eras {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.walk-era {
  display: block;
  cursor: pointer;
}

.walk-era-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 100%;
  min-height: 76px;
  padding: 12px 14px;
  border: 1px solid var(--sb-control-border);
  background: var(--p-surface);
}

.walk-era:hover .walk-era-card {
  border-color: var(--p-ink-3);
}

.walk-era input:checked + .walk-era-card {
  border-color: var(--p-gold);
  background: var(--p-terracotta-tint);
  box-shadow: inset 0 0 0 1px var(--p-gold);
}

.walk-era input:focus-visible + .walk-era-card {
  outline: 2px solid var(--p-gold);
  outline-offset: 2px;
}

.walk-era-year {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--p-gold);
}

.walk-era-name {
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  line-height: 1.15;
  color: var(--p-ink);
}

.walk .field {
  margin-top: 18px;
}

/* Γ΄ their words */
.walk-words + .walk-words {
  margin-top: 24px;
}

.walk-words:first-child {
  margin-top: 0;
}

.walk-says {
  gap: 10px;
  font-family: var(--p-font-display);
  font-size: var(--t-lg);
  font-weight: 500;
  letter-spacing: 0;
  text-transform: none;
  color: var(--p-ink);
}

.walk-words-input,
.walk-question-input {
  font-family: var(--p-font-serif);
  font-size: 17px;
  line-height: 1.6;
}

.walk-words-input {
  min-height: 124px;
}

.input[aria-invalid='true'] {
  border-color: var(--p-gold);
  box-shadow: inset 3px 0 0 var(--p-gold);
}

/* Ε΄ quarrels: whole sentences, one to a line */
.walk-quarrels {
  flex-direction: column;
  align-items: stretch;
}

.walk-quarrel {
  justify-content: flex-start;
  padding: 10px 14px;
  font-family: var(--p-font-serif);
  font-size: 15px;
  line-height: 1.4;
  text-align: left;
}

.walk-row-tight {
  margin-top: 4px;
}

/* What still needs an answer, in the Oracle's quiet voice */
.walk-problems {
  margin-top: 18px;
}

.walk-problems.empty {
  margin-top: 0;
}

.walk-problems p,
.walk-problems-list li {
  padding: 10px 14px 10px 16px;
  border-left: 2px solid var(--p-gold);
  background: color-mix(in srgb, var(--p-gold) 9%, transparent);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink);
}

.walk-problems p + p {
  margin-top: 6px;
}

.walk-problems-label {
  margin-bottom: 8px;
  padding: 0 !important;
  border: none !important;
  background: none !important;
  font-family: var(--p-font-inscription);
  font-size: 12px !important;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-ink-3) !important;
}

.walk-problems-list ul {
  display: grid;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.walk-problems-list li {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 4px 12px;
}

.walk-nav {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 26px;
  padding-top: 18px;
  border-top: 1px solid var(--p-line);
}

.walk-nav-gap {
  flex: 1 1 auto;
}

.walk-enter-hint {
  font-size: var(--t-xs);
  color: var(--p-ink-4);
  white-space: nowrap;
}

.walk-next {
  min-width: 150px;
}

.walk-speak {
  min-height: 56px;
  padding: 0 28px;
  font-size: var(--t-md);
}

.walk-speak-scroll {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.6;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* Write it yourself: a way to the full form, never styled as a delete */
.walk-foot {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 2px 14px;
  margin-top: 10px;
}

.walk-write-link {
  margin-left: -12px;
  color: var(--p-ink-2);
}

.walk-write-link:hover:not(:disabled) {
  color: var(--p-gold);
  background: var(--p-terracotta-tint);
}

.walk-stylus {
  width: 16px;
  height: 16px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.walk-write-hint {
  font-size: var(--t-xs);
  line-height: 1.5;
  color: var(--p-ink-4);
}

.walk-foot .draft-note {
  margin-left: auto;
}

/* The stage, held up as a small scroll */
.walk-scroll {
  padding: clamp(20px, 4vw, 34px);
  border: 1px solid var(--p-line-strong);
  box-shadow: var(--p-shadow-2);
}

.walk-scroll-eyebrow {
  margin: 0 0 8px;
}

.walk-scroll-title {
  margin: 0 0 16px;
  font-family: var(--p-font-display);
  font-size: clamp(1.5rem, 3.4vw, 2rem);
  font-weight: 500;
  line-height: 1.15;
  color: var(--p-ink);
}

.walk-rows {
  margin: 0;
}

.walk-row {
  display: grid;
  grid-template-columns: 10rem minmax(0, 1fr) auto;
  grid-template-areas: 'label text change';
  align-items: baseline;
  column-gap: 18px;
  padding: 8px 0;
  border-top: 1px solid var(--p-line);
}

.walk-row dt {
  display: contents;
}

.walk-row dt > span {
  grid-area: label;
  padding-top: 4px;
  font-family: var(--p-font-inscription);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--p-ink-3);
}

.walk-row dt > span:lang(zh) {
  font-family: var(--p-font-serif);
  letter-spacing: 0.06em;
}

.walk-change {
  grid-area: change;
  min-height: 40px;
  padding: 0 2px;
}

.walk-row dd {
  grid-area: text;
  align-self: center;
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: 16px;
  line-height: 1.55;
  color: var(--p-ink);
}

.walk-said + .walk-said {
  margin-top: 8px;
}

.walk-said strong {
  margin-right: 8px;
  font-weight: 600;
}

.walk-quote {
  font-style: italic;
}

.walk-taken {
  margin-top: 14px;
}

/* One set of answers gives way to the next */
.walk-enter-active,
.walk-leave-active {
  transition: opacity 0.26s ease, transform 0.26s ease;
}

.walk-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.walk-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

/* Write it yourself: the way back */
.form-return {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 18px;
  margin-bottom: 28px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--p-line);
  scroll-margin-top: 88px;
}

.form-return .p-button {
  scroll-margin-top: 88px;
}

.form-return-note {
  margin: 0;
  font-size: var(--t-sm);
  color: var(--p-ink-3);
}

/* Below a wide screen her alcove becomes a band above the answers */
@media (max-width: 959px) {
  .walk-grid {
    grid-template-columns: minmax(0, 1fr);
    grid-template-areas:
      'pythia'
      'answers';
    row-gap: 22px;
  }

  .walk-pythia {
    position: relative;
    top: auto;
    min-height: 0;
    box-shadow: none;
  }

  .walk-pythia-img {
    object-position: 26% 42%;
    opacity: 0.4;
  }

  .walk-pythia-shade {
    background:
      linear-gradient(180deg, rgba(7, 9, 13, 0.5) 0%, rgba(7, 9, 13, 0.62) 45%, rgba(7, 9, 13, 0.94) 100%),
      linear-gradient(90deg, rgba(7, 9, 13, 0.1), rgba(7, 9, 13, 0.55));
  }

  .walk-pythia-glow {
    left: 52px;
    top: 50px;
    width: 200px;
    height: 180px;
  }

  .walk-pythia-body {
    padding: 18px 18px 22px;
  }

  .walk-pythia-sign {
    flex-direction: row;
    align-items: center;
    text-align: left;
  }

  .walk-tripod {
    width: 56px;
    height: 56px;
    stroke-width: 1.05;
    filter: drop-shadow(0 0 8px rgba(240, 182, 96, 0.45));
  }

  .walk-vapour {
    stroke-width: 0.75;
  }

  .walk-vapour.late {
    stroke-width: 0.65;
  }

  .walk-oracle {
    align-items: flex-start;
    gap: 4px;
  }

  .walk-delphi {
    font-size: 13px;
    letter-spacing: 0.34em;
    margin-right: 0;
  }

  .walk-speech {
    margin-top: 0;
    padding-top: 16px;
  }

  .walk-speech::before {
    display: none;
  }

  .walk-question {
    font-size: 1.75rem;
  }

  .walk-voice {
    max-width: none;
    margin-top: 8px;
    font-size: 1.125rem;
  }

  .walk-step {
    padding-top: 22px;
  }
}

@media (max-width: 640px) {
  .walk-eras {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .walk-head {
    gap: 12px;
  }

  .walk-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas:
      'label change'
      'text text';
    padding: 4px 0 12px;
  }

  .walk-enter-hint {
    display: none;
  }

  .walk-next,
  .walk-speak {
    flex: 1 1 auto;
    min-width: 0;
  }

  .walk-speak {
    padding: 0 16px;
  }

  .walk-inline .walk-add {
    padding: 0 16px;
  }

  .chip-note {
    min-height: 0;
  }

  .walk-foot .draft-note {
    margin-left: 0;
  }
}

/* Text boxes grow with what is written, where the browser can. */
.walk-words-input,
.walk-question-input {
  field-sizing: content;
  max-height: 22em;
}

.walk-question-input {
  min-height: 7.2em;
}

/* Chinese has no italic; slanted hanzi read as a fault, so the Oracle speaks upright,
   in a serif that carries hanzi. */
.walk-question:lang(zh),
.walk-voice:lang(zh) {
  font-family: var(--p-font-serif);
  font-style: normal;
}

.walk-question:lang(zh) {
  font-weight: 500;
  line-height: 1.3;
}

.walk-voice:lang(zh) {
  font-size: 1.1rem;
  line-height: 1.7;
}

.walk-quote:lang(zh),
.walk-said em:lang(zh),
.draft-note:lang(zh),
.chip-note.idle:lang(zh),
.walk .input:lang(zh)::placeholder {
  font-style: normal;
}

@media (hover: none) {
  .walk-enter-hint {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .walk-enter-active,
  .walk-leave-active,
  .speech-enter-active,
  .speech-leave-active {
    transition: none;
  }

  .walk-vapour,
  .walk-pythia-glow {
    animation: none;
  }

  /* The vapour held still: one thread, standing in the air. */
  .walk-vapour {
    stroke-dasharray: none;
    opacity: 0.7;
  }

  .walk-vapour.late {
    display: none;
  }

  .walk-pythia-glow {
    transition: none;
  }
}
</style>
