import { createRouter, createWebHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Process from '../views/MainView.vue'
import SimulationView from '../views/SimulationView.vue'
import SimulationRunView from '../views/SimulationRunView.vue'
import ReportView from '../views/ReportView.vue'
import InteractionView from '../views/InteractionView.vue'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: Home
  },
  {
    path: '/process/:projectId',
    name: 'Process',
    component: Process,
    props: true
  },
  {
    path: '/simulation/:simulationId',
    name: 'Simulation',
    component: SimulationView,
    props: true
  },
  {
    path: '/simulation/:simulationId/start',
    name: 'SimulationRun',
    component: SimulationRunView,
    props: true
  },
  {
    path: '/report/:reportId',
    name: 'Report',
    component: ReportView,
    props: true
  },
  {
    path: '/interaction/:reportId',
    name: 'Interaction',
    component: InteractionView,
    props: true
  },
  // The Chronicles: every gathering Athens has held, as a place of its own.
  {
    path: '/chronicles',
    name: 'Chronicles',
    component: () => import('../views/ChroniclesView.vue')
  },
  // A gathering's permanent link, from any of its ids. It finds the furthest
  // act reached and steps aside for it; a station (hearing, gathering, agora,
  // chronicle, film, symposium) opens that act instead.
  {
    path: '/gathering/:id/:station?',
    name: 'Gathering',
    component: () => import('../views/GatheringView.vue'),
    props: true
  }
]

const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

// A hash can name something the act draws only after it has read its record
// (the film sits at the end of the Chronicle, below chapters that arrive a
// moment later). Wait for it to appear and for the page around it to settle.
const HASH_TARGETS = { '#film': ['#film', '.chronicle-film'] }
const findHashTarget = (hash) => {
  const selectors = HASH_TARGETS[hash] || [hash]
  for (const selector of selectors) {
    try {
      const el = document.querySelector(selector)
      if (el) return el
    } catch (e) {
      return null // not a selector: nothing to find
    }
  }
  return null
}
const waitForHashTarget = (hash, timeout = 8000) =>
  new Promise((resolve) => {
    const started = Date.now()
    let lastTop = null
    let steady = 0
    const look = () => {
      const el = findHashTarget(hash)
      const late = Date.now() - started > timeout
      if (el) {
        const top = Math.round(el.getBoundingClientRect().top + window.scrollY)
        steady = top === lastTop ? steady + 1 : 0
        lastTop = top
        if (steady >= 4 || late) return resolve(el)
      } else if (late) {
        return resolve(null)
      }
      setTimeout(look, 150)
    }
    look()
  })

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    // Back and forward return to where the visitor was.
    if (savedPosition) return savedPosition
    // A link into a place on another page: open the page, then go to the place.
    if (to.hash && to.path !== from.path) {
      return waitForHashTarget(to.hash).then((el) => {
        if (!el) return false
        // Clear of the sticky header, with a little air above.
        const top = el.getBoundingClientRect().top + window.scrollY - 88
        window.scrollTo({ top: Math.max(0, top), behavior: reducedMotion() ? 'auto' : 'smooth' })
        return false
      })
    }
    // A new page starts at its top; the same page (a query, an in-page anchor) stays put.
    if (to.path !== from.path) return { top: 0 }
    return false
  }
})

export default router
