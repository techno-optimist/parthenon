<template>
  <router-view v-slot="{ Component }">
    <transition name="act" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>
</template>

<script setup>
// 使用 Vue Router 来管理页面
</script>

<style>
/* 全局样式重置 */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

#app {
  font-family: var(--p-font-body);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--p-ink);
  background-color: transparent;
}

/* 滚动条样式 */
::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: var(--p-surface-2);
}

::-webkit-scrollbar-thumb {
  background: var(--p-line-strong);
  border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
  background: var(--p-ink-4);
}

/* 全局按钮样式 */
button {
  font-family: inherit;
}

/* Between acts: the lights go down and come up. Never a hard cut. */
.act-enter-active { transition: opacity 0.7s ease; }
.act-leave-active { transition: opacity 0.45s ease; }
.act-enter-from, .act-leave-to { opacity: 0; }
</style>
