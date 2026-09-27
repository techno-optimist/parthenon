// First, before the router reads the address: a link that carries the word
// (?invite=CODE) gives it to the page and loses it from the address bar.
import './parthenon/inviteLink.js'
import { createApp } from 'vue'
import './assets/parthenon.css'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { loadInstance } from './parthenon/instance.js'
import { applyMediaVars } from './parthenon/mediaVars.js'

// The stills the styles paint with, under the page's base (parthenon/mediaVars.js).
applyMediaVars(document.documentElement)

const app = createApp(App)

app.use(router)
app.use(i18n)

app.mount('#app')

// What this city can do, and whether it is on the public steps: read once for
// every page (parthenon/access.js). The home reads it afresh for the day's limits.
loadInstance()
