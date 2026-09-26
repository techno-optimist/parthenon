<template>
  <div class="chronicles-page">
    <header class="cp-bar">
      <router-link to="/" class="cp-brand" :aria-label="$t('parthenon.navHome')"><ParthenonBrand /></router-link>
      <p class="cp-place" aria-hidden="true">
        <span class="cp-place-mark">ΧΡΟΝΙΚΑ</span>
        <span class="cp-place-name">{{ $t('history.title') }}</span>
      </p>
      <nav class="cp-links" :aria-label="$t('parthenon.navSections')">
        <router-link :to="{ path: '/', hash: '#stages' }" class="cp-link">{{ $t('parthenon.chronicles.page.hold') }}</router-link>
      </nav>
    </header>

    <!-- The threshold: the Scribe's table by lamplight, the Acropolis beyond -->
    <section class="cp-threshold" aria-labelledby="cp-title">
      <div class="cp-scene" aria-hidden="true"></div>
      <div class="cp-shade" aria-hidden="true"></div>
      <div class="cp-copy wrap">
        <p class="p-eyebrow">
          <span lang="grc">ΤΑ ΧΡΟΝΙΚΑ</span>
          <span aria-hidden="true"> · </span>
          <span>{{ $t('parthenon.chronicles.page.eyebrow') }}</span>
        </p>
        <h1 id="cp-title" class="cp-title">{{ $t('history.title') }}</h1>
        <p class="cp-lede">{{ $t('parthenon.chronicles.page.lede') }}</p>
      </div>
    </section>
    <div class="p-meander cp-rule" aria-hidden="true"></div>

    <main class="cp-shelf wrap">
      <HistoryDatabase mode="page" />
    </main>

    <footer class="cp-foot wrap">
      <p class="cp-maxim" lang="grc">ΓΝΩΘΙ ΣΕΑΥΤΟΝ</p>
      <p class="cp-maxim-gloss">{{ $t('parthenon.maxim') }}</p>
      <div class="cp-foot-row">
        <router-link to="/" class="p-button ghost cp-back">
          <span aria-hidden="true">←</span>
          <span>{{ $t('parthenon.chronicles.page.back') }}</span>
        </router-link>
        <LanguageSwitcher />
      </div>
    </footer>
  </div>
</template>

<script setup>
// The Chronicles as a place: the Scribe's room at night, and on its shelf
// every gathering Athens has held. Each tablet opens a filmstrip of that
// gathering's acts; the shelf itself is HistoryDatabase in its page mode.
import HistoryDatabase from '../components/HistoryDatabase.vue'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'
import ParthenonBrand from '../components/ParthenonBrand.vue'
</script>

<style scoped>
.chronicles-page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--p-bg);
  color: var(--p-ink-2);
  font-family: var(--p-font-body);
}

.wrap {
  width: min(1240px, 100% - 2 * var(--p-gutter));
  margin-inline: auto;
}

/* One header, as in every act */
.cp-bar {
  position: sticky;
  top: 0;
  z-index: 30;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 16px;
  height: var(--p-header-h);
  padding: 0 var(--p-gutter);
  background: rgba(11, 14, 19, 0.86);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--p-line);
}

.cp-brand {
  justify-self: start;
  display: inline-flex;
  align-items: center;
  min-width: 40px;
  min-height: 40px;
  text-decoration: none;
  color: inherit;
}

.cp-place {
  display: flex;
  align-items: baseline;
  gap: 12px;
  margin: 0;
  white-space: nowrap;
}

.cp-place-mark {
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  letter-spacing: var(--track-inscription);
  color: var(--p-gold);
}

.cp-place-name {
  font-family: var(--p-font-display);
  font-size: var(--t-xl);
  font-weight: 500;
  line-height: 1;
  color: var(--p-ink);
}

.cp-links {
  justify-self: end;
  display: flex;
  align-items: center;
}

.cp-link {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  font-family: var(--p-font-inscription);
  font-size: var(--t-xs);
  font-weight: 600;
  letter-spacing: var(--track-inscription);
  text-transform: uppercase;
  color: var(--p-ink);
  text-decoration: none;
  white-space: nowrap;
  transition: color 0.2s ease;
}

.cp-link:hover {
  color: var(--p-gold);
}

/* The threshold */
.cp-threshold {
  position: relative;
  display: flex;
  align-items: flex-end;
  min-height: clamp(320px, 46vh, 460px);
  padding: 72px 0 40px;
  overflow: hidden;
  isolation: isolate;
}

.cp-scene {
  position: absolute;
  inset: 0;
  z-index: -2;
  background-image: url('/media/acts/chronicle.jpg');
  background-size: cover;
  background-position: center 58%;
  animation: settle 2.4s cubic-bezier(0.22, 1, 0.36, 1) both;
}

.cp-shade {
  position: absolute;
  inset: 0;
  z-index: -1;
  background:
    linear-gradient(180deg, rgba(11, 14, 19, 0.5) 0%, rgba(11, 14, 19, 0.25) 40%, rgba(11, 14, 19, 0.97) 100%),
    linear-gradient(90deg, rgba(11, 14, 19, 0.8) 0%, rgba(11, 14, 19, 0.15) 70%);
}

@keyframes settle {
  from { transform: scale(1.05); opacity: 0.6; }
  to { transform: scale(1); opacity: 1; }
}

.cp-copy .p-eyebrow {
  margin: 0 0 14px;
}

.cp-title {
  margin: 0 0 14px;
  font-family: var(--p-font-display);
  font-size: clamp(48px, 7vw, 92px);
  font-weight: 500;
  line-height: 0.98;
  letter-spacing: -0.01em;
  color: var(--p-ink);
}

.cp-lede {
  margin: 0;
  max-width: 44ch;
  font-family: var(--p-font-serif);
  font-style: italic;
  font-size: var(--t-lg);
  line-height: 1.5;
  color: var(--p-ink-2);
}

.cp-rule {
  opacity: 0.35;
}

.cp-shelf {
  flex: 1;
  padding: 40px 0 24px;
}

/* The foot: the maxim, the way back, the languages */
.cp-foot {
  margin-top: 72px;
  padding: 56px 0 40px;
  border-top: 1px solid var(--p-line);
  text-align: center;
}

.cp-maxim {
  margin: 0;
  font-family: var(--p-font-inscription);
  font-size: var(--t-sm);
  font-weight: 600;
  letter-spacing: 0.34em;
  color: var(--p-gold);
}

.cp-maxim-gloss {
  margin: 6px 0 24px;
  font-family: var(--p-font-display);
  font-style: italic;
  font-size: var(--t-lg);
  color: var(--p-ink-3);
}

.cp-foot-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 16px 28px;
}

.cp-back {
  min-height: 44px;
}

@media (max-width: 899px) {
  .cp-bar {
    grid-template-columns: auto 1fr;
  }

  .cp-place {
    display: none;
  }
}

@media (max-width: 640px) {
  .cp-bar {
    padding-inline: 16px;
  }

  .cp-bar :deep(.p-brand-word) {
    display: none;
  }

  .cp-link {
    letter-spacing: 0.08em;
  }

  .cp-threshold {
    min-height: 300px;
    padding: 56px 0 28px;
  }

  .cp-scene {
    background-position: 30% 58%;
  }

  .cp-lede {
    font-size: var(--t-md);
  }

  .cp-shelf {
    padding-top: 28px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .cp-scene {
    animation: none;
  }
}
</style>
