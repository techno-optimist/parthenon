<template>
  <span
    class="citizen-coin p-coin"
    :class="[`size-${size}`, { 'has-face': !!face }]"
    :style="{ '--role': roleColor }"
    :role="label ? 'img' : undefined"
    :aria-label="label || undefined"
    :aria-hidden="label ? undefined : 'true'"
  >
    <span class="initial" aria-hidden="true">{{ initial }}</span>
    <img v-if="face" :src="face" alt="" loading="lazy" decoding="async" :class="{ loaded }" @load="loaded = true" @error="broken = true" />
  </span>
</template>

<script setup>
// A citizen's face: their portrait when the painters have made one, else the
// first letter of their name, always ringed in their role's colour so the same
// person reads the same in the Web, the Agora, the Chronicle and the Symposium.
import { computed, ref, watch } from 'vue'
import { roleColorVar } from '../parthenon/vocabulary.js'

const props = defineProps({
  name: { type: String, default: '' },
  type: { type: String, default: '' }, // entity type from the engine (e.g. PublicOfficial)
  portrait: { type: String, default: '' }, // URL, or '' for the initial
  size: { type: String, default: 'md' }, // sm 30 | md 40 | lg 56 | xl 96
  label: { type: String, default: '' }, // set when the coin stands alone without a visible name
  color: { type: String, default: '' } // override the role colour (e.g. the Scribe)
})

const broken = ref(false)
const loaded = ref(false)
watch(() => props.portrait, () => { broken.value = false; loaded.value = false })

const face = computed(() => (!broken.value && props.portrait) || '')
const roleColor = computed(() => props.color || roleColorVar(props.type))
const initial = computed(() => {
  const n = String(props.name || '').trim().replace(/^(the|dr\.?|father|mr\.?|mrs\.?|ms\.?)\s+/i, '')
  return (n.charAt(0) || '·').toUpperCase()
})
</script>

<style scoped>
.citizen-coin {
  position: relative;
  overflow: hidden;
  width: 40px;
  height: 40px;
  font-size: var(--t-lg);
}

.citizen-coin.size-sm { width: 30px; height: 30px; font-size: var(--t-md); }
.citizen-coin.size-lg { width: 56px; height: 56px; font-size: var(--t-xl); }
.citizen-coin.size-xl { width: 96px; height: 96px; font-size: var(--t-2xl); }

.citizen-coin img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: center 30%;
  opacity: 0;
  transition: opacity 0.4s ease;
}

.citizen-coin img.loaded {
  opacity: 1;
}

.citizen-coin.has-face {
  border-width: 1.5px;
  border-color: var(--role);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--role) 16%, transparent);
}

.initial {
  line-height: 1;
}
</style>
