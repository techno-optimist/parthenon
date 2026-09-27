// The one who had the floor on the steps: found, as the seat of honour finds
// them, by the gathering's first scroll. Pure; no Vue, so node can test it.
// The backend keeps the same table (backend/app/services/floor.py) and decides
// who answers; the page only needs a name, a Chinese name and a seat.
import { speakers } from './speakers.js'
import { arrivals } from './arrivals/index.js'

// Where the card's name is not the one who answers: the sand speaks as Sand,
// and the Symposium's table is led by Socrates.
export const FLOOR_OVERRIDES = {
  'arrival-when-sand-speaks.md': { name: 'Sand', zh: '沙' },
  'arrival-symposium-machine-minds.md': { name: 'Socrates', zh: '苏格拉底' }
}

// The backend's name_key: accents dropped, lower case, words only. A name with
// no Latin letters (a Chinese name) keeps its own characters, spaces removed.
export const nameKey = (s) => {
  const k = String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
  return k || String(s || '').toLowerCase().replace(/\s+/g, '')
}

// Who had the floor for this scroll, or null when the scroll is not one of ours.
export const floorOf = (fileName, lists = { speakers, arrivals }) => {
  if (!fileName) return null
  const speaker = (lists.speakers || []).find((s) => s.fileName === fileName)
  const arrival = speaker ? null : (lists.arrivals || []).find((a) => a.fileName === fileName)
  const item = speaker || arrival
  if (!item) return null
  const over = FLOOR_OVERRIDES[fileName]
  return {
    fileName,
    kind: speaker ? 'speaker' : 'arrival',
    id: item.id,
    name: over ? over.name : item.name,
    zhName: over ? over.zh : item.zh?.name || ''
  }
}

// Their name in the visitor's language.
export const floorName = (floor, locale) => {
  if (!floor) return ''
  if (String(locale || '').startsWith('zh') && floor.zhName) return floor.zhName
  return floor.name
}

// Their couch, when they also sat among the citizens: the first citizen who bears their name.
export const floorSeat = (floor, citizens) => {
  if (!floor || !Array.isArray(citizens)) return null
  const keys = new Set([nameKey(floor.name), floor.zhName ? nameKey(floor.zhName) : ''].filter(Boolean))
  const found = citizens.find((c) => c && keys.has(nameKey(c.name)))
  return found ? found.idx : null
}
