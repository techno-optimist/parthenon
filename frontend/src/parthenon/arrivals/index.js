// The Arrivals: the philosophers step off the Parthenon steps into 2026.
// Each scenario is its own module; this list sets their order on the page.
import socrates from './socrates-answer-machine.js'
import plato from './plato-new-cave.js'
import aristotle from './aristotle-self-weaving-loom.js'
import heraclitus from './heraclitus-never-same-model.js'
import diogenes from './diogenes-lamp-bots.js'
import epicurus from './epicurus-garden-griefbots.js'
import hypatia from './hypatia-machine-library.js'
import prometheus from './prometheus-trial.js'
import symposium from './symposium-machine-minds.js'
import sand from './when-sand-speaks.js'

export const arrivals = [
  socrates,
  plato,
  aristotle,
  heraclitus,
  diogenes,
  epicurus,
  hypatia,
  prometheus,
  symposium,
  sand
]

export const arrivalSeedFile = (arrival) =>
  new File([arrival.seed], arrival.fileName, { type: 'text/markdown' })
