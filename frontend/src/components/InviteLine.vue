<template>
  <!-- The word that opens the steps to speech: one quiet slip of parchment, one field.
       Not a form of its own, so it can stand beside (never inside) the form it opens. -->
  <div ref="slip" class="invite-line p-paper" role="group" :aria-labelledby="ids.lead" :aria-describedby="`${ids.hint}${line ? ` ${ids.line}` : ''}`">
    <p :id="ids.lead" class="invite-lead">{{ $t('parthenon.public.invite.lead') }}</p>
    <p :id="ids.hint" class="invite-hint">{{ $t('parthenon.public.invite.hint') }}</p>
    <div class="invite-row">
      <label class="invite-sr" :for="ids.field">{{ $t('parthenon.public.invite.label') }}</label>
      <input
        :id="ids.field"
        ref="field"
        v-model="code"
        class="invite-field"
        type="text"
        name="parthenon-invite"
        inputmode="text"
        autocomplete="off"
        autocapitalize="off"
        autocorrect="off"
        spellcheck="false"
        maxlength="256"
        :placeholder="$t('parthenon.public.invite.placeholder')"
        :aria-invalid="line ? 'true' : undefined"
        @keydown.enter.prevent="give"
        @input="malformed = false; said = ''"
      />
      <button type="button" class="p-button invite-give" :disabled="!code.trim() || checking" :aria-busy="checking ? 'true' : undefined" @click="give">{{ $t('parthenon.public.invite.give') }}</button>
    </div>
    <p v-if="line" :id="ids.line" class="invite-wrong" role="status">{{ line }}</p>
  </div>
</template>

<script setup>
// Asked only at the moment speech needs it (before 'Let Athens speak', before
// a first question, before the Oracle drafts). The word is kept for this
// browser (parthenon/access.js giveInvite) and the caller goes on ('given').
// The word is checked with the city first (POST /api/parthenon/invite), so a
// word it does not know is said here, calmly, before anything is asked of it;
// a city that cannot check (an older one, or the network) takes it as given,
// and the call it opens says if it was wrong, which brings this line back.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { checkInvite } from '../api/parthenon.js'
import { access, calmCode, calmLine, giveInvite } from '../parthenon/access.js'
import { cleanInvite, presentSlip, showSlip } from '../parthenon/invite.js'

const props = defineProps({
  // Another calm line to say here (a limit on words tried, say), in the city's words.
  note: { type: String, default: '' },
  // Take the focus when it appears (it appears because the visitor asked to speak).
  autofocus: { type: Boolean, default: true }
})
const emit = defineEmits(['given'])
const { t } = useI18n()

const uid = `invite-${Math.random().toString(36).slice(2, 9)}`
const ids = { lead: `${uid}-lead`, hint: `${uid}-hint`, field: `${uid}-field`, line: `${uid}-line` }

const slip = ref(null)
const field = ref(null)
const code = ref('')
const malformed = ref(false)
const checking = ref(false)
// The city's own calm line from the check (too many words tried this hour).
const said = ref('')

const line = computed(() => {
  if (props.note) return props.note
  if (said.value) return said.value
  if (malformed.value || access.inviteWrong) return t('parthenon.public.invite.wrong')
  return ''
})

const give = async () => {
  if (checking.value) return
  const clean = cleanInvite(code.value)
  if (!clean) {
    malformed.value = !!code.value.trim()
    return
  }
  said.value = ''
  checking.value = true
  try {
    await checkInvite(clean)
  } catch (err) {
    const refused = calmCode(err)
    // Not known: the API client has marked it wrong (access.inviteWrong); the line says so.
    if (refused === 'invite_needed') return
    if (refused) {
      said.value = calmLine(err)
      return
    }
    // The city could not check it: taken as given.
  } finally {
    checking.value = false
  }
  if (!giveInvite(clean)) return
  code.value = ''
  emit('given', clean)
}

// The slip comes into view whole, above the act bar, before its field takes
// the caret (on a phone the field and 'Give the word' could otherwise sit under the bar).
const present = () => presentSlip(slip.value, field.value)

onMounted(() => {
  if (!props.autofocus) return
  nextTick(present)
})

// A calm line said at the slip's foot (a word not known, a limit) is brought
// into view too, so it is never said under the act bar.
watch(line, (now, was) => {
  if (now && now !== was) nextTick(() => showSlip(slip.value))
})

defineExpose({ focus: present })
</script>

<style scoped>
.invite-line {
  margin: 14px 0 0;
  padding: 14px 16px 16px;
  max-width: 60ch;
  border-left: 2px solid var(--p-gold);
  background: var(--p-surface);
  color: var(--p-ink);
  text-align: left;
  /* Brought into view clear of the fixed header and the act bar (presentSlip). */
  scroll-margin: calc(var(--p-header-h, 64px) + 12px) 0 calc(var(--p-way-h, 52px) + env(safe-area-inset-bottom, 0px) + 16px);
}

.invite-lead {
  margin: 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-md);
  line-height: 1.5;
  color: var(--p-ink);
  text-wrap: pretty;
}

.invite-hint {
  margin: 4px 0 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  font-style: italic;
  line-height: 1.5;
  color: var(--p-ink-2);
}

html:lang(zh) .invite-hint {
  font-style: normal;
}

.invite-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}

.invite-field {
  flex: 1 1 14ch;
  min-width: 0;
  min-height: 48px;
  padding: 0 12px;
  border: 1px solid var(--p-control-border);
  border-radius: var(--p-radius);
  background: var(--p-bg);
  color: var(--p-ink);
  font-family: var(--p-font-mono);
  font-size: 1rem; /* 16px: a phone does not zoom into the field */
  letter-spacing: var(--track-mono);
}

.invite-field::placeholder {
  color: var(--p-ink-3);
  font-family: var(--p-font-serif);
  letter-spacing: 0;
}

.invite-field:focus-visible {
  outline: 2px solid var(--p-gold);
  outline-offset: 2px;
}

.invite-field[aria-invalid='true'] {
  border-color: var(--p-error);
}

.invite-give {
  flex: 0 0 auto;
}

.invite-wrong {
  margin: 10px 0 0;
  font-family: var(--p-font-serif);
  font-size: var(--t-sm);
  line-height: 1.5;
  color: var(--p-ink-2);
}

.invite-sr {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 480px) {
  .invite-give {
    flex: 1 1 100%;
  }
}
</style>
