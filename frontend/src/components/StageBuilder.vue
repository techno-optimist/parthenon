<template>
  <div class="stage-builder">
    <p class="visually-hidden" aria-live="polite">{{ announcement }}</p>

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
              <span class="format-name">{{ f.label }}</span>
              <span class="format-blurb">{{ f.blurb }}</span>
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
            <span class="pill">{{ e.label }}</span>
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
        <p class="part-help">{{ $t('parthenon.builder.matterHelp') }}</p>

        <div class="field">
          <label :for="ids.topic" class="field-label">{{ $t('parthenon.builder.topicLabel') }}</label>
          <textarea
            :id="ids.topic"
            v-model="stage.topic"
            class="input"
            rows="5"
            maxlength="3000"
            :placeholder="$t('parthenon.builder.topicPlaceholder')"
          ></textarea>
        </div>

        <div v-if="showSparks && sparks.length" class="chip-group">
          <p :id="ids.sparks" class="chip-group-label">{{ $t('parthenon.builder.sparksLabel') }}</p>
          <div class="chip-row" role="group" :aria-labelledby="ids.sparks">
            <button
              v-for="s in sparks"
              :key="s.label"
              type="button"
              class="chip spark"
              :class="{ chosen: stage.topic.trim() === s.topic }"
              :aria-pressed="stage.topic.trim() === s.topic"
              :title="s.topic"
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
            :placeholder="stage.title.trim() ? '' : preview.title"
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
            {{ $t('parthenon.builder.speakersUnder', { format: currentFormat.label, range: rangeText(currentFormat), missing: currentFormat.min - namedCount }) }}
          </template>
          <template v-else-if="rangeState === 'over'">
            {{ $t('parthenon.builder.speakersOver', { format: currentFormat.label, range: rangeText(currentFormat), extra: namedCount - currentFormat.max }) }}
          </template>
          <template v-else>
            {{ $t('parthenon.builder.speakersOk', { format: currentFormat.label, range: rangeText(currentFormat), named: namedCount }) }}
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
                  <span class="speaker-head-name">{{ displayName(sp) }}</span>
                  <span v-if="figureOf(sp)" class="speaker-head-greek">{{ figureOf(sp).greek }}</span>
                  <span v-if="sp.role.trim()" class="speaker-head-role">{{ sp.role }}</span>
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
              :title="`${f.known} (${f.lived})`"
              :aria-label="speakerForFigure(f) ? $t('parthenon.builder.onStageAria', { name: f.name }) : $t('parthenon.builder.summonAria', { name: f.name })"
              @click="addFigure(f)"
            >
              <span class="chip-coin" aria-hidden="true">{{ f.letter }}</span>
              <span class="chip-name">{{ f.name }}</span>
              <span v-if="speakerForFigure(f)" class="chip-state" aria-hidden="true">{{ $t('parthenon.builder.onStage') }}</span>
            </button>
          </div>
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
              :title="g.role"
              :aria-label="speakerForGuest(g) ? $t('parthenon.builder.onStageAria', { name: g.name }) : $t('parthenon.builder.inviteAria', { name: g.name })"
              @click="addGuest(g)"
            >
              <span class="chip-coin modern" aria-hidden="true">{{ initialOf(g.name) }}</span>
              <span class="chip-name">{{ g.name }}</span>
              <span v-if="speakerForGuest(g)" class="chip-state" aria-hidden="true">{{ $t('parthenon.builder.onStage') }}</span>
            </button>
          </div>
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
              :title="p.description"
              :aria-label="$t('parthenon.builder.addPresetAria', { name: p.name })"
              @click="addPreset(p, i)"
            >
              <span class="chip-plus" aria-hidden="true">+</span>
              <span class="chip-name">{{ p.name }}</span>
            </button>
          </div>
          <p v-else class="empty-line small">{{ $t('parthenon.builder.presetsAllAdded') }}</p>
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
            :placeholder="defaultNext"
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
          <svg class="tripod" viewBox="0 0 40 40" aria-hidden="true">
            <path d="M8 13h24M10 13c0 7 4 10 10 10s10-3 10-10" />
            <path d="M13 22 8 36M27 22l5 14M20 23v13" />
            <path d="M16 9c0-3 3-3 3-6M22 9c0-3 3-3 3-6" />
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
            <span class="begin-arrow" aria-hidden="true">→</span>
          </button>
          <p v-if="taken" class="taken-line" role="status">
            {{ $t('parthenon.builder.taken', { file: taken }) }}
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
            <article class="scroll-sheet p-paper" v-html="previewHtml"></article>
            <p class="scroll-note">
              {{ $t('parthenon.builder.previewNote') }} <code>{{ preview.fileName }}</code>
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
  emptyStage,
  speakerFromFigure,
  stageHints,
  stageProblems,
  suggestQuestion,
} from '../parthenon/composeStage.js'
import { figures, modernGuests } from '../parthenon/roster.js'

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

function rangeText(f) {
  if (f.min === f.max) {
    return f.min === 1 ? t('parthenon.builder.voicesOne') : t('parthenon.builder.voicesExact', { count: f.min })
  }
  return t('parthenon.builder.voicesRange', { min: f.min, max: f.max })
}

const settingIsUnedited = () => {
  const current = stage.setting.trim()
  return !current || ERAS.some((e) => e.setting && e.setting === current)
}

function onEraChange(era) {
  if (settingIsUnedited()) stage.setting = era.setting
}

// ---------------------------------------------------------------------------
// Γ΄ matter

const sparks = computed(() => {
  const list = tm('parthenon.builder.sparks')
  if (!Array.isArray(list)) return []
  return list
    .map((item) => ({ label: asMessage(item && item.label), topic: asMessage(item && item.topic) }))
    .filter((s) => s.label && s.topic)
})

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
const suggestedQuestion = computed(() => suggestQuestion(stage))
const defaultNext = computed(() => {
  if (stage.happensNext.trim()) return ''
  // A seed holding nothing but the form has no user text, so its last section is the default line.
  const { markdown } = composeStageSeed({ format: stage.format })
  return (markdown.split('\n## What happens next\n')[1] || '').trim()
})

function useSuggestion() {
  stage.question = suggestedQuestion.value
  // The button goes away once the question is filled; keep focus on the question.
  focusById(ids.questionInput)
}

const problems = computed(() => [
  ...stageProblems(stage),
  ...repeatedNames.value.map((name) =>
    tx('problemRepeatedName', 'More than one speaker is called {name}. Give each speaker a name of their own.', { name })
  ),
])
const hints = computed(() => stageHints(stage))

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
    question: seed.question,
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
}

/** Put a roster figure on the stage (or reveal them if already there). */
function summon(figureId) {
  const figure = figureById(figureId)
  if (!figure) return false
  const existing = speakerForFigure(figure)
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
  font-size: 11px;
  font-weight: 700;
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
  font-size: 10.5px;
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
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--p-ink-4);
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
  font-size: 10px;
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
  font-size: 11px;
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
  font-size: 10px;
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
  font-size: 11px;
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
  font-size: 11px;
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
  padding: 1px 6px;
  border: 1px solid var(--p-terracotta);
  background: var(--p-surface-3);
  font-family: var(--p-font-inscription);
  font-size: 9.5px;
  font-weight: 700;
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
  fill: none;
  stroke: var(--p-ink-3);
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.oracle-copy {
  flex: 1 1 260px;
  min-width: 0;
}

.oracle-eyebrow {
  margin-bottom: 4px;
  font-family: var(--p-font-inscription);
  font-size: 11px;
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
  font-size: 11px;
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
</style>
