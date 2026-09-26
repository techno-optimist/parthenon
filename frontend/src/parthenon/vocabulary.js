// The city's words. Everything the engine calls something else (platforms,
// entity types, tie names, action codes, usernames) passes through here before
// a visitor reads it. Pure module: no Vue, no DOM.

export const PLATFORMS = {
  twitter: { name: 'the Agora', title: 'The Agora', short: 'Agora' },
  reddit: { name: 'the Stoa', title: 'The Stoa', short: 'Stoa' }
}

export const platformName = (id, form = 'name') => {
  const key = String(id || '').toLowerCase()
  return PLATFORMS[key]?.[form] || String(id || '')
}

// Entity types come from an LLM-written ontology, so the map is a floor:
// anything unknown is split from PascalCase into plain words.
const ENTITY_TYPES = {
  Person: 'citizen',
  Entity: '',
  Organization: 'organization',
  Aisystem: 'AI system',
  AISystem: 'AI system',
  AIModel: 'AI model',
  PublicOfficial: 'public official',
  CorporateExecutive: 'company director',
  TechCompany: 'technology company',
  CivicCampaign: 'civic campaign',
  CulturalPractitioner: 'keeper of culture',
  LocalBusinessOwner: 'local business owner',
  Fisher: 'fisher',
  Student: 'student',
  PublicFigure: 'public figure',
  Government: 'government',
  MediaOutlet: 'news outlet',
  Company: 'company',
  Location: 'place',
  Place: 'place',
  Event: 'event'
}

export const entityTypeName = (type) => {
  const raw = String(type || '').trim()
  if (!raw) return ''
  if (raw in ENTITY_TYPES) return ENTITY_TYPES[raw]
  return raw
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .toLowerCase()
    .replace(/\bai\b/g, 'AI')
}

// Role families give a citizen one colour that follows them through the
// Web, the Agora, the Chronicle and the Symposium.
const FAMILIES = {
  people: ['Person', 'Fisher', 'PublicOfficial', 'CorporateExecutive', 'CulturalPractitioner', 'LocalBusinessOwner', 'Student', 'PublicFigure', 'Professor', 'Teacher', 'Journalist', 'Parent', 'Worker', 'Farmer', 'Priest', 'Doctor', 'Lawyer', 'Judge'],
  institutions: ['Organization', 'TechCompany', 'Company', 'Government', 'Council', 'Institution', 'School', 'University', 'MediaOutlet', 'Court', 'Union'],
  movements: ['CivicCampaign', 'Campaign', 'Movement', 'Party', 'Group', 'Coalition'],
  machines: ['Aisystem', 'AISystem', 'AIModel', 'Machine', 'Robot', 'Tutor'],
  places: ['Location', 'Place', 'City', 'Island', 'Region', 'Building'],
  things: ['Entity', 'Thing', 'Object', 'Document', 'Law', 'Clause', 'Contract', 'Project']
}

export const roleFamily = (type) => {
  const raw = String(type || '')
  for (const [family, types] of Object.entries(FAMILIES)) {
    if (types.includes(raw)) return family
  }
  const words = entityTypeName(raw)
  if (/\b(ai|model|machine|bot|system)\b/i.test(words)) return 'machines'
  if (/\b(campaign|movement|party|coalition|association|group)\b/i.test(words)) return 'movements'
  if (/\b(company|organi[sz]ation|council|school|university|court|union|outlet|ministry|board)\b/i.test(words)) return 'institutions'
  if (/\b(place|city|island|region|bay|quarry|building|square)\b/i.test(words)) return 'places'
  if (/\b(clause|law|contract|compact|proposal|document|plan|policy|product)\b/i.test(words)) return 'things'
  return 'people'
}

// Colour per family, as CSS custom properties from parthenon.css.
export const ROLE_COLOR_VAR = {
  people: 'var(--p-gold)',
  institutions: 'var(--p-aegean)',
  movements: 'var(--p-olive)',
  machines: 'var(--p-ink)',
  places: 'var(--p-ochre)',
  things: 'var(--p-ink-4)'
}

export const roleColorVar = (type) => ROLE_COLOR_VAR[roleFamily(type)]

// The role as a label: "Public official", "AI system", "Citizen".
export const roleLabel = (type) => {
  const words = entityTypeName(type)
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : ''
}

// Ties in the Web of Athens. Activity ties are verbs in the past tense.
const TIES = {
  WORKS_FOR: 'works for',
  OPERATED_BY: 'operated by',
  OWNED_BY: 'owned by',
  LEADS: 'leads',
  MEMBER_OF: 'member of',
  REPRESENTS: 'represents',
  NEGOTIATES_WITH: 'negotiates with',
  ADVISES: 'advises',
  RESPONDS_TO: 'responds to',
  RESPOND_TO: 'responds to',
  SUPPORTS: 'supports',
  OPPOSES: 'opposes',
  RELATES_TO: 'is tied to',
  POSTED: 'spoke',
  COMMENTED: 'answered',
  COMMENTED_ON_POST_OF: 'answered',
  LIKED_POST: 'nodded',
  LIKED_POST_OF: 'nodded to',
  LIKED_COMMENT: 'nodded',
  LIKED_COMMENT_OF: 'nodded to',
  DISLIKED_POST: 'shook their head',
  DISLIKED_POST_OF: 'shook their head at',
  DISLIKED_COMMENT: 'shook their head',
  DISLIKED_COMMENT_OF: 'shook their head at',
  REPOSTED: 'repeated',
  QUOTED: 'quoted',
  FOLLOWS: 'follows',
  MUTED: 'turned away from',
  SEARCHED: 'asked around',
  SEARCHED_USER: 'asked after',
  ACTED: 'acted'
}

export const tieName = (name) => {
  const raw = String(name || '').trim()
  if (!raw) return ''
  if (raw in TIES) return TIES[raw]
  return raw.replace(/_/g, ' ').toLowerCase()
}

// Ties that are bookkeeping of the square rather than the shape of the city.
const ACTIVITY_TIES = new Set(['POSTED', 'COMMENTED', 'COMMENTED_ON_POST_OF', 'LIKED_POST', 'LIKED_POST_OF', 'LIKED_COMMENT', 'LIKED_COMMENT_OF', 'DISLIKED_POST', 'DISLIKED_POST_OF', 'DISLIKED_COMMENT', 'DISLIKED_COMMENT_OF', 'REPOSTED', 'QUOTED', 'FOLLOWS', 'MUTED', 'SEARCHED', 'SEARCHED_USER', 'ACTED'])

export const isActivityTie = (name) => ACTIVITY_TIES.has(String(name || '').trim())

// Nodes the memory keeps for the platforms themselves. They are not citizens.
export const isPlatformNode = (name) => /^(twitter|reddit|x|the agora|the stoa|agora|stoa)$/i.test(String(name || '').trim())

// What a citizen does in the square, as a verb in the present tense.
const ACTIONS = {
  CREATE_POST: 'speaks',
  POST: 'speaks',
  CREATE_COMMENT: 'answers',
  COMMENT: 'answers',
  REPLY: 'answers',
  LIKE_POST: 'nods',
  LIKE_COMMENT: 'nods',
  LIKE: 'nods',
  UPVOTE: 'nods',
  DISLIKE_POST: 'shakes their head',
  DISLIKE_COMMENT: 'shakes their head',
  DISLIKE: 'shakes their head',
  DOWNVOTE: 'shakes their head',
  REPOST: 'repeats',
  QUOTE_POST: 'quotes',
  QUOTE: 'quotes',
  FOLLOW: 'follows',
  UNFOLLOW: 'walks away from',
  MUTE: 'turns away',
  SEARCH_POSTS: 'asks around',
  SEARCH_USER: 'asks after someone',
  SEARCH: 'asks around',
  DO_NOTHING: 'listens',
  IDLE: 'listens',
  REFRESH: 'looks around',
  TREND: 'looks around',
  INTERVIEW: 'is questioned'
}

export const actionVerb = (code) => {
  const raw = String(code || '').trim().toUpperCase()
  if (!raw) return ''
  if (raw in ACTIONS) return ACTIONS[raw]
  return raw.replace(/_/g, ' ').toLowerCase()
}

// Speech is what the Chronicle quotes; the rest is the crowd moving.
export const isSpeech = (code) => ['CREATE_POST', 'POST', 'CREATE_COMMENT', 'COMMENT', 'REPLY', 'QUOTE_POST', 'QUOTE'].includes(String(code || '').toUpperCase())

// "despina_nomikou_466" -> "Despina Nomikou". A real display name wins.
export const citizenName = (name, username) => {
  const display = String(name || '').trim()
  if (display && !/^[a-z0-9]+(_[a-z0-9]+)*_\d+$/i.test(display) && !/^@/.test(display)) return display
  const handle = String(username || display || '').replace(/^@/, '').replace(/_\d+$/, '')
  return handle
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

// Engine identifiers have no place in the play.
export const stripIds = (text) =>
  String(text ?? '')
    .replace(/\b(proj|sim|report|task|mirofish|graph)_[0-9a-f]{6,}\b/gi, '')
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\s+([,.:;])/g, '$1')
    .replace(/[:\s]+$/g, '')
    .trim()

// The five acts, in order, with their Greek numerals.
export const ACTS = [
  { n: 1, numeral: 'Α΄', key: 'hearing', route: 'Process', scene: '/media/acts/hearing.jpg' },
  { n: 2, numeral: 'Β΄', key: 'gathering', route: 'Simulation', scene: '/media/acts/gathering.jpg' },
  { n: 3, numeral: 'Γ΄', key: 'agora', route: 'SimulationRun', scene: '/media/acts/agora.jpg' },
  { n: 4, numeral: 'Δ΄', key: 'chronicle', route: 'Report', scene: '/media/acts/chronicle.jpg' },
  { n: 5, numeral: 'Ε΄', key: 'symposium', route: 'Interaction', scene: '/media/acts/symposium.jpg' }
]

// Story-sized run lengths instead of round counts. Minutes are rough and
// come from real runs at about 40 seconds a round with twenty citizens.
export const RUN_LENGTHS = [
  { id: 'afternoon', rounds: 12, hours: 12, minutes: '8 to 12' },
  { id: 'day', rounds: 24, hours: 24, minutes: '15 to 25' },
  { id: 'threeDays', rounds: 72, hours: 72, minutes: '45 to 70' },
  { id: 'week', rounds: 168, hours: 168, minutes: '2 to 3 hours' }
]
