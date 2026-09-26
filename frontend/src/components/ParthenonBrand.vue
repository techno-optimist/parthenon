<template>
  <span class="p-brand" :class="{ large }">
    <svg class="p-brand-mark" viewBox="0 0 32 28" aria-hidden="true">
      <path d="M16 1 31 8.6H1Z" />
      <rect x="1" y="9.6" width="30" height="2.6" />
      <rect x="3" y="13.4" width="3" height="9.6" />
      <rect x="9.25" y="13.4" width="3" height="9.6" />
      <rect x="14.5" y="13.4" width="3" height="9.6" />
      <rect x="19.75" y="13.4" width="3" height="9.6" />
      <rect x="26" y="13.4" width="3" height="9.6" />
      <rect x="1" y="24" width="30" height="1.7" />
      <rect x="0" y="26.3" width="32" height="1.7" />
    </svg>
    <span class="p-brand-word">Parthenon</span>
  </span>
</template>

<script setup>
defineProps({
  large: { type: Boolean, default: false }
})
</script>

<style scoped>
.p-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--p-ink);
  user-select: none;
}

.p-brand-mark {
  width: 26px;
  height: 23px;
  fill: var(--p-terracotta);
  flex-shrink: 0;
}

.p-brand-word {
  font-family: var(--p-font-inscription);
  font-weight: 600;
  font-size: 17px;
  letter-spacing: 0.2em;
  text-transform: uppercase;
  line-height: 1;
}

.large .p-brand-mark {
  width: 32px;
  height: 28px;
}

.large .p-brand-word {
  font-size: 20px;
}
</style>
