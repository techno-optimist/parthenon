// The city's words. Everything the engine calls something else (platforms,
// entity types, tie names, action codes, usernames) passes through here before
// a visitor reads it. Pure module: no Vue, no DOM.
//
// The words follow the visitor's language. i18n/index.js calls
// setVocabularyLocale() at start and whenever the language changes; every
// function that returns visible words takes an optional last `locale`
// argument that wins over the module's. English and Chinese have words of
// their own; any other language reads the English ones.
import { withBase } from './base.js'

let currentLocale = 'en'
// An optional reader of the app's own (reactive) locale. Reading it inside
// a computed or a render makes that view follow a change of language; the
// module itself stays free of Vue.
let localeSource = null

const normal = (locale) => String(locale || 'en').slice(0, 2).toLowerCase() || 'en'
const langOf = (locale) => (normal(locale) === 'zh' ? 'zh' : 'en')

const visitorLocale = () => {
  if (localeSource) {
    try {
      const live = localeSource()
      if (live) currentLocale = normal(live)
    } catch {
      localeSource = null
    }
  }
  return currentLocale
}
const useLang = (locale) => langOf(locale ?? visitorLocale())

export const setVocabularyLocale = (locale) => {
  currentLocale = normal(locale)
  return currentLocale
}
export const getVocabularyLocale = () => visitorLocale()
export const followVocabularyLocale = (read) => {
  localeSource = typeof read === 'function' ? read : null
}

// Chinese has no spaces between words and no capitals.
const hasHan = (text) => /[㐀-鿿]/.test(String(text || ''))

export const PLATFORMS = {
  twitter: { name: 'the Agora', title: 'The Agora', short: 'Agora' },
  reddit: { name: 'the Stoa', title: 'The Stoa', short: 'Stoa' }
}
const PLATFORMS_ZH = {
  twitter: { name: '广场', title: '广场', short: '广场' },
  reddit: { name: '柱廊', title: '柱廊', short: '柱廊' }
}

export const platformName = (id, form = 'name', locale) => {
  const key = String(id || '').toLowerCase()
  const table = useLang(locale) === 'zh' ? PLATFORMS_ZH : PLATFORMS
  return table[key]?.[form] || String(id || '')
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

const splitType = (raw) =>
  raw
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .toLowerCase()

const englishTypeName = (raw) => {
  if (raw in ENTITY_TYPES) return ENTITY_TYPES[raw]
  return splitType(raw).replace(/\bai\b/g, 'AI')
}

// The same roles in Chinese. Whole types first; anything else is put
// together word by word when every word is known, and read in English when
// one is not (half a translation reads worse than none).
const ENTITY_TYPES_ZH = {
  Person: '市民',
  Entity: '',
  Organization: '组织',
  Aisystem: 'AI 系统',
  AISystem: 'AI 系统',
  AIModel: 'AI 模型',
  PublicOfficial: '公职人员',
  CorporateExecutive: '公司高管',
  TechCompany: '科技公司',
  CivicCampaign: '市民运动',
  CulturalPractitioner: '文化守护者',
  LocalBusinessOwner: '本地店主',
  Fisher: '渔民',
  Student: '学生',
  PublicFigure: '公众人物',
  Government: '政府',
  MediaOutlet: '新闻媒体',
  Company: '公司',
  Location: '地点',
  Place: '地点',
  Event: '事件',
  AcademicExpert: '学者',
  Accuser: '控告者',
  AdvocacyGroup: '倡议团体',
  CitizenJuror: '市民陪审员',
  FamilyMember: '家人',
  Follower: '追随者',
  Interventionist: '辅导教师',
  Parent: '家长',
  Philosopher: '哲人',
  Playwright: '剧作家',
  Politician: '政治人物',
  ReligiousLeader: '宗教领袖',
  SchoolBoard: '校董会',
  SchoolBoardMember: '校董会成员',
  Sophist: '智者',
  Teacher: '教师',
  VendorRepresentative: '供应商代表',
  Professor: '教授',
  Journalist: '记者',
  Worker: '工人',
  Farmer: '农夫',
  Priest: '祭司',
  Priestess: '女祭司',
  Doctor: '医生',
  Nurse: '护士',
  Lawyer: '律师',
  Judge: '法官',
  Juror: '陪审员',
  Council: '议会',
  CityCouncil: '市议会',
  Institution: '机构',
  School: '学校',
  University: '大学',
  Court: '法庭',
  Union: '工会',
  Campaign: '运动',
  Movement: '运动',
  Party: '党派',
  Group: '团体',
  Coalition: '联盟',
  Machine: '机器',
  Robot: '机器人',
  Tutor: '辅导者',
  City: '城市',
  Island: '岛屿',
  Region: '地区',
  Building: '建筑',
  Thing: '事物',
  Object: '物件',
  Document: '文书',
  Law: '法律',
  Clause: '条款',
  Contract: '合同',
  Project: '项目'
}

const TYPE_WORDS_ZH = {
  academic: '学术', accuser: '控告者', activist: '活动人士', advisor: '顾问', adviser: '顾问', advocacy: '倡议',
  advocate: '倡导者', agency: '机构', ai: 'AI', artist: '艺术家', assembly: '议事会', association: '协会',
  author: '作者', bank: '银行', board: '委员会', business: '商户', campaign: '运动', citizen: '市民',
  city: '市', civic: '市民', coalition: '联盟', committee: '委员会', community: '社区', company: '公司',
  corporate: '企业', council: '议会', court: '法庭', creator: '创作者', cultural: '文化', developer: '开发者',
  doctor: '医生', elder: '长者', engineer: '工程师', executive: '高管', expert: '专家', family: '家庭',
  farmer: '农夫', fisher: '渔民', fisherman: '渔民', follower: '追随者', founder: '创始人', group: '团体',
  government: '政府', guild: '行会', hotel: '酒店', hotelier: '酒店业者', influencer: '网红', investor: '投资人',
  journalist: '记者', judge: '法官', juror: '陪审员', lab: '实验室', laboratory: '实验室', lawyer: '律师',
  leader: '领袖', librarian: '图书馆员', library: '图书馆', local: '本地', mayor: '市长', media: '媒体',
  member: '成员', merchant: '商人', model: '模型', movement: '运动', nurse: '护士', official: '官员',
  organization: '组织', organisation: '组织', outlet: '机构', owner: '业主', parent: '家长', parents: '家长',
  party: '党派', philosopher: '哲人', playwright: '剧作家', poet: '诗人', politician: '政治人物', priest: '祭司',
  professor: '教授', public: '公共', quarryman: '采石工', regulator: '监管者', religious: '宗教',
  representative: '代表', research: '研究', researcher: '研究者', resident: '居民', retired: '退休',
  scholar: '学者', school: '学校', singer: '歌者', slave: '奴隶', soldier: '士兵', sophist: '智者',
  startup: '初创公司', student: '学生', system: '系统', teacher: '教师', tech: '科技', technology: '科技',
  translator: '译者', union: '工会', university: '大学', vendor: '供应商', veteran: '老兵', voter: '选民',
  worker: '工人', writer: '作家', young: '年轻', youth: '青年'
}

const chineseTypeName = (raw) => {
  if (raw in ENTITY_TYPES_ZH) return ENTITY_TYPES_ZH[raw]
  const words = splitType(raw).split(/\s+/).filter(Boolean)
  if (words.length && words.every((w) => w in TYPE_WORDS_ZH)) {
    return words.map((w) => TYPE_WORDS_ZH[w]).join('').replace(/^AI(?=[㐀-鿿])/, 'AI ')
  }
  return englishTypeName(raw)
}

export const entityTypeName = (type, locale) => {
  const raw = String(type || '').trim()
  if (!raw) return ''
  if (hasHan(raw)) return raw
  return useLang(locale) === 'zh' ? chineseTypeName(raw) : englishTypeName(raw)
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
  // Families are read from the English words whatever the visitor's language.
  const words = entityTypeName(raw, 'en')
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

// The role as a label: "Public official", "AI system", "Citizen" (公职人员,
// AI 系统, 市民 in Chinese, which has no capitals).
export const roleLabel = (type, locale) => {
  const words = entityTypeName(type, locale)
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

// The same ties in Chinese, each able to stand alone or between two names.
const TIES_ZH = {
  WORKS_FOR: '效力于',
  OPERATED_BY: '运营方为',
  OWNED_BY: '归属于',
  LEADS: '领导',
  MEMBER_OF: '隶属于',
  REPRESENTS: '代表',
  NEGOTIATES_WITH: '谈判对象为',
  ADVISES: '辅佐',
  RESPONDS_TO: '回应',
  RESPOND_TO: '回应',
  SUPPORTS: '支持',
  OPPOSES: '反对',
  RELATES_TO: '牵系',
  POSTED: '发言',
  COMMENTED: '回应',
  COMMENTED_ON_POST_OF: '回应',
  LIKED_POST: '点头',
  LIKED_POST_OF: '点头赞同',
  LIKED_COMMENT: '点头',
  LIKED_COMMENT_OF: '点头赞同',
  DISLIKED_POST: '摇头',
  DISLIKED_POST_OF: '摇头不认',
  DISLIKED_COMMENT: '摇头',
  DISLIKED_COMMENT_OF: '摇头不认',
  REPOSTED: '复述',
  QUOTED: '引述',
  FOLLOWS: '追随',
  MUTED: '不再理会',
  SEARCHED: '四处打听',
  SEARCHED_USER: '打听',
  ACTED: '有所行动',
  // Ties the Scribe often names in the Web.
  ALLIED_WITH: '结盟',
  ALLIES_WITH: '结盟',
  CRITICIZES: '批评',
  CRITICISES: '批评',
  CHALLENGES: '质疑',
  ACCUSES: '控告',
  DEFENDS: '辩护',
  INFLUENCES: '影响',
  TEACHES: '教导',
  STUDIES: '研习',
  FUNDS: '资助',
  SPONSORS: '资助',
  EMPLOYS: '雇用',
  REGULATES: '监管',
  GOVERNS: '治理',
  COMPETES_WITH: '竞争',
  COLLABORATES_WITH: '合作',
  WORKS_WITH: '共事',
  PARTNERS_WITH: '合作',
  LOCATED_IN: '位于',
  LIVES_IN: '住在',
  BASED_IN: '驻于',
  PART_OF: '属于',
  BELONGS_TO: '属于',
  PARTICIPATES_IN: '参与',
  ORGANIZES: '组织',
  PROPOSES: '提议',
  CREATED: '创立',
  CREATES: '创造',
  FOUNDED: '创立',
  USES: '使用',
  DEVELOPS: '开发',
  PRODUCES: '出产',
  AFFECTS: '波及',
  IMPACTS: '波及',
  CONCERNS: '关乎',
  MENTIONS: '提及',
  REPORTS_ON: '报道',
  CARES_FOR: '照料',
  FEARS: '畏惧',
  TRUSTS: '信任',
  DISTRUSTS: '不信任',
  KNOWS: '认识',
  MARRIED_TO: '配偶为',
  PARENT_OF: '养育',
  FRIEND_OF: '结交',
  STUDENT_OF: '师从',
  TEACHER_OF: '教导',
  RIVAL_OF: '对抗'
}

export const tieName = (name, locale) => {
  const raw = String(name || '').trim()
  if (!raw) return ''
  if (hasHan(raw)) return raw
  if (useLang(locale) === 'zh') {
    const key = raw.toUpperCase().replace(/[\s-]+/g, '_')
    if (key in TIES_ZH) return TIES_ZH[key]
  }
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

const ACTIONS_ZH = {
  CREATE_POST: '发言',
  POST: '发言',
  CREATE_COMMENT: '回答',
  COMMENT: '回答',
  REPLY: '回答',
  LIKE_POST: '点头',
  LIKE_COMMENT: '点头',
  LIKE: '点头',
  UPVOTE: '点头',
  DISLIKE_POST: '摇头',
  DISLIKE_COMMENT: '摇头',
  DISLIKE: '摇头',
  DOWNVOTE: '摇头',
  REPOST: '复述',
  QUOTE_POST: '引述',
  QUOTE: '引述',
  FOLLOW: '追随',
  UNFOLLOW: '转身离开',
  MUTE: '不再理会',
  SEARCH_POSTS: '四处打听',
  SEARCH_USER: '打听某人',
  SEARCH: '四处打听',
  DO_NOTHING: '静听',
  IDLE: '静听',
  REFRESH: '环顾四周',
  TREND: '环顾四周',
  INTERVIEW: '接受询问'
}

export const actionVerb = (code, locale) => {
  const raw = String(code || '').trim().toUpperCase()
  if (!raw) return ''
  const table = useLang(locale) === 'zh' ? ACTIONS_ZH : ACTIONS
  if (raw in table) return table[raw]
  // An unknown deed in Chinese is still a deed, not an engine code.
  if (useLang(locale) === 'zh') return '有所行动'
  return raw.replace(/_/g, ' ').toLowerCase()
}

// Speech is what the Chronicle quotes; the rest is the crowd moving.
export const isSpeech = (code) => ['CREATE_POST', 'POST', 'CREATE_COMMENT', 'COMMENT', 'REPLY', 'QUOTE_POST', 'QUOTE'].includes(String(code || '').toUpperCase())

// "despina_nomikou_466" -> "Despina Nomikou". A real display name wins.
export const citizenName = (name, username) => {
  const display = String(name || '').trim()
  // Run-together engine names ("CitizenJury") get their spaces back.
  if (display && !/^[a-z0-9]+(_[a-z0-9]+)*_\d+$/i.test(display) && !/^@/.test(display)) {
    return /\s/.test(display) ? display : display.replace(/([a-z])([A-Z])/g, '$1 $2')
  }
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
  { n: 1, numeral: 'Α΄', key: 'hearing', route: 'Process', scene: withBase('/media/acts/hearing.jpg') },
  { n: 2, numeral: 'Β΄', key: 'gathering', route: 'Simulation', scene: withBase('/media/acts/gathering.jpg') },
  { n: 3, numeral: 'Γ΄', key: 'agora', route: 'SimulationRun', scene: withBase('/media/acts/agora.jpg') },
  { n: 4, numeral: 'Δ΄', key: 'chronicle', route: 'Report', scene: withBase('/media/acts/chronicle.jpg') },
  { n: 5, numeral: 'Ε΄', key: 'symposium', route: 'Interaction', scene: withBase('/media/acts/symposium.jpg') }
]

// Story-sized run lengths instead of round counts. Minutes are rough and
// come from real runs at about 40 seconds a round with twenty citizens.
// `minutes` reads in the visitor's language. A week is a span in hours in
// both ("2 to 3 hours", "2 至 3 小时"): it names its own unit, so every
// caller asks spansHours() and gives it the phrasing without "minutes"
// (约 2 至 3 小时, never 小时 分钟).
const RUN_MINUTES = {
  afternoon: { en: '8 to 12', zh: '8 至 12' },
  day: { en: '15 to 25', zh: '15 至 25' },
  threeDays: { en: '45 to 70', zh: '45 至 70' },
  week: { en: '2 to 3 hours', zh: '2 至 3 小时' }
}
export const runLengthMinutes = (id, locale) => {
  const row = RUN_MINUTES[typeof id === 'object' && id ? id.id : id]
  return row ? row[useLang(locale)] : ''
}
const runLength = (id, rounds) => ({
  id,
  rounds,
  hours: rounds,
  get minutes() { return runLengthMinutes(id) }
})
export const RUN_LENGTHS = [
  runLength('afternoon', 12),
  runLength('day', 24),
  runLength('threeDays', 72),
  runLength('week', 168)
]

// ---------------------------------------------------------------------------
// Shared phrasing, so every act says the same thing the same way.

// Where a citizen stood. The engine writes supportive / opposing / neutral /
// observer and a sentiment from -1 to 1. Four sides everywhere.
// form: 'side' ('For' | 'Against' | 'Undecided' | 'Watching'), 'phrase'
// ('stood for it'), or 'key' ('for' | 'against' | 'undecided' | 'watching').
export const STANCE_SIDES = ['for', 'against', 'undecided', 'watching']
const STANCE_WORDS = {
  en: {
    side: { for: 'For', against: 'Against', undecided: 'Undecided', watching: 'Watching' },
    phrase: { for: 'stood for it', against: 'stood against it', undecided: 'was undecided', watching: 'watched without taking a side' },
    strong: { for: 'stood firmly for it', against: 'stood firmly against it' }
  },
  zh: {
    side: { for: '支持', against: '反对', undecided: '未定', watching: '旁观' },
    phrase: { for: '支持', against: '反对', undecided: '尚未决定', watching: '旁观，不表态' },
    strong: { for: '坚决支持', against: '坚决反对' }
  }
}

export const stanceKey = (stance, bias) => {
  const s = String(stance || '').toLowerCase()
  if (/support|favou?r|\bfor\b|pro/.test(s)) return 'for'
  if (/oppos|against|\bcon\b|reject/.test(s)) return 'against'
  if (/observ|watch|onlooker|report/.test(s)) return 'watching'
  if (/neutral|undecided|unsure|mixed/.test(s)) return 'undecided'
  const b = Number(bias)
  if (Number.isFinite(b) && b >= 0.35) return 'for'
  if (Number.isFinite(b) && b <= -0.35) return 'against'
  return 'undecided'
}

// The locale defaults to the visitor's (see setVocabularyLocale).
export const stanceWords = (stance, bias, form = 'side', locale) => {
  const key = stanceKey(stance, bias)
  if (form === 'key') return key
  const words = STANCE_WORDS[useLang(locale)] || STANCE_WORDS.en
  if (form === 'phrase') {
    const b = Math.abs(Number(bias))
    if (Number.isFinite(b) && b >= 0.75 && words.strong[key]) return words.strong[key]
    return words.phrase[key]
  }
  return words.side[key]
}

// Α΄ Β΄ Γ΄ ... with the keraia, for chapters and acts (1..24).
const GREEK_LETTERS = ['Α', 'Β', 'Γ', 'Δ', 'Ε', 'ΣΤ', 'Ζ', 'Η', 'Θ', 'Ι', 'ΙΑ', 'ΙΒ', 'ΙΓ', 'ΙΔ', 'ΙΕ', 'ΙΣΤ', 'ΙΖ', 'ΙΗ', 'ΙΘ', 'Κ', 'ΚΑ', 'ΚΒ', 'ΚΓ', 'ΚΔ']
export const greekNumeral = (n) => {
  const i = Math.trunc(Number(n)) - 1
  return i >= 0 && i < GREEK_LETTERS.length ? `${GREEK_LETTERS[i]}΄` : String(n)
}

// The engine's words turned into the city's, for text the engine wrote about
// itself (never for citizens' own speech).
const CITY_WORDS = [
  [/\bsimulated (agents|citizens|individuals|users|people)\b/gi, 'citizens'],
  [/\b(agents|simulated individuals)\b/gi, 'citizens'],
  [/\bagent\b/gi, 'citizen'],
  [/\bthe simulation\b/gi, 'the gathering'],
  [/\bsimulations\b/gi, 'gatherings'],
  [/\bsimulation\b/gi, 'gathering'],
  [/\bsimulated\b/gi, ''],
  [/\bTwitter\b/g, 'the Agora'],
  [/\bReddit\b/g, 'the Stoa'],
  [/\b(knowledge )?graph\b/gi, 'Web of Athens'],
  [/\bprediction report\b/gi, 'Chronicle'],
  // The squares are the Agora and the Stoa, never "the platforms".
  [/\bon the platforms representing civic conversation\b/gi, 'in the Agora and the Stoa'],
  [/\b(?:both|the two|two|the) (?:social[- ]media |online )?platforms\b/gi, 'the Agora and the Stoa'],
  [/\bsocial[- ]media\b/gi, 'the squares'],
  // A Chronicle reckons and foretells; it does not predict.
  [/\bpredictions\b/gi, 'reckonings'],
  [/\bprediction\b/gi, 'reckoning'],
  [/\bpredicted\b/gi, 'foretold'],
  [/\bpredicts\b/gi, 'foretells'],
  [/\bpredicting\b/gi, 'foretelling'],
  [/\bpredict\b/gi, 'foretell'],
  [/\bLLM\b/g, 'the Scribe']
]
// The same for text the engine wrote in Chinese. English text stays English
// (the city's English words), even when the visitor reads in Chinese.
const CITY_WORDS_ZH = [
  [/模拟(智能体|个体|用户|人物|人群)/g, '市民'],
  [/智能体|\s*\b[Aa]gents?\b\s*/g, '市民'],
  [/虚拟(个体|用户)/g, '市民'],
  [/模拟世界/g, '城中'],
  [/模拟环境/g, '集会'],
  [/模拟/g, '集会'],
  [/(预测|推演)报告/g, '编年史'],
  [/报告智能体|ReportAgent/g, '书记官'],
  [/(知识)?图谱/g, '雅典之网'],
  // An English name set in Chinese loses the spaces around it.
  [/\s*\bTwitter\b\s*|推特/g, '广场'],
  [/\s*\bReddit\b\s*/g, '柱廊'],
  [/\s*\bLLM\b\s*|大语言模型|大模型/g, '书记官']
]
export const cityWords = (text, locale) => {
  let out = String(text ?? '')
  if (useLang(locale) === 'zh' && hasHan(out)) {
    for (const [re, rep] of CITY_WORDS_ZH) out = out.replace(re, rep)
    return out.replace(/市民市民/g, '市民').replace(/[ \t]{2,}/g, ' ').trim()
  }
  // A common word that opened its sentence keeps its capital ("Agents" becomes
  // "Citizens"); a name the engine wrote (Twitter) is replaced as it stands.
  for (const [re, rep] of CITY_WORDS) {
    out = re.flags.includes('i') && rep
      ? out.replace(re, (m) => (/^\p{Lu}/u.test(m) ? rep.charAt(0).toUpperCase() + rep.slice(1) : rep))
      : out.replace(re, rep)
  }
  return out.replace(/\bthe the\b/gi, 'the').replace(/[ \t]{2,}/g, ' ').replace(/\s+([,.;:])/g, '$1').trim()
}

// A typographic voice per class of citizen (Pentiment's lesson): philosophers
// and poets in Cormorant italic, officials and institutions with an inscription
// lead-in, machines in mono, everyone else in Spectral. The easy-read toggle
// maps every voice to 'plain'.
export const VOICES = ['elder', 'official', 'machine', 'common', 'plain']
export const voiceOf = (type) => {
  const raw = String(type || '')
  const words = entityTypeName(raw, 'en')
  const family = roleFamily(raw)
  if (family === 'machines') return 'machine'
  if (family === 'institutions' || family === 'movements') return 'official'
  if (/\b(philosopher|poet|priest|priestess|prophet|oracle|elder|singer|keeper of culture|scholar|teacher)\b/i.test(words)) return 'elder'
  if (/\b(official|mayor|judge|magistrate|archon|director|executive|minister|councillor|legislator)\b/i.test(words)) return 'official'
  return 'common'
}

// ---------------------------------------------------------------------------
// Which language a piece of the gathering's own text is in, so a screen
// reader picks the right voice (WCAG 3.1.2): 'zh' when Han characters make
// up more than about 30% of its letters, else 'en'. A Chinese Chronicle in
// the English city is read in Chinese, and the other way round.
export const textLang = (text) => {
  const s = String(text ?? '')
  const han = (s.match(/[㐀-鿿豈-﫿]/g) || []).length
  if (!han) return 'en'
  const latin = (s.match(/[A-Za-z]/g) || []).length
  return han / (han + latin) > 0.3 ? 'zh' : 'en'
}

// A length on the steps is a span of minutes, or (for a week) of hours; a
// span of hours carries its own unit ("2 to 3 hours", "2 至 3 小时").
export const spansHours = (minutes) => /hour|小时/i.test(String(minutes ?? ''))

// The prepared scrolls set their cast lists with dashes ("Plato — backs the
// labels"). On the page the first becomes a colon and any later one a comma.
// Display only: the scroll the court reads is never changed.
export const undash = (line) => {
  let first = true
  return String(line ?? '').replace(/\s+[—–]\s+/g, () => {
    if (first) {
      first = false
      return ': '
    }
    return ', '
  })
}

// Straight quotes set as a printer would: " at the start of a word opens,
// any other closes; ' at the start of a word opens, any other is an
// apostrophe. Only for English prose; code and addresses are left alone by
// the caller.
export const smartQuotes = (text) =>
  String(text ?? '')
    .replace(/(^|[\s([{—–/-])"(?=\S)/g, '$1“')
    .replace(/"/g, '”')
    .replace(/(^|[\s([{—–/-])'(?=[\p{L}\p{N}])/gu, '$1‘')
    .replace(/'/g, '’')

// ---------------------------------------------------------------------------
// Where a gathering on the shelf stands, from its history row: whether it has
// been argued, whether its Chronicle is written, and the furthest act reached.
const RAN_STATES = ['starting', 'running', 'stopping', 'paused', 'stopped', 'completed']
export const gatheringStanding = (row) => {
  const r = row || {}
  const runner = String(r.runner_status || '').toLowerCase()
  const status = String(r.status || '').toLowerCase()
  const reportStatus = String(r.report_status || '').toLowerCase()
  const reportId = r.report_id || ''
  const argued = Number(r.current_round) > 0 || RAN_STATES.includes(runner) || RAN_STATES.includes(status)
  const written = !!reportId && reportStatus === 'completed'
  const act = reportId && reportStatus !== 'failed' ? 4 : argued || reportId ? 3 : r.simulation_id ? 2 : 1
  return {
    act,
    argued,
    written,
    reportId,
    reportStatus,
    simulationId: r.simulation_id || '',
    projectId: r.project_id || '',
    currentRound: Math.max(0, Number(r.current_round) || 0),
    totalRounds: Math.max(0, Number(r.total_rounds) || 0),
    citizens: Number(r.profiles_count) || Number(r.entities_count) || 0
  }
}

// The gathering a scroll leads back to: the furthest along, then the newest.
export const bestGathering = (rows) =>
  [...(Array.isArray(rows) ? rows : [])]
    .filter((r) => r && r.simulation_id)
    .sort((a, b) =>
      gatheringStanding(b).act - gatheringStanding(a).act ||
      String(b.created_at || '').localeCompare(String(a.created_at || ''))
    )[0] || null

// Every station of the Way a gathering has reached, as routes. An act passes
// its own knowledge on top; the Way never links the act the visitor is in.
export const wayLinks = (row, { projectId } = {}) => {
  const out = {}
  const s = gatheringStanding(row)
  const project = projectId || s.projectId
  if (project) out[1] = { name: 'Process', params: { projectId: project } }
  if (s.simulationId) {
    out[2] = { name: 'Simulation', params: { simulationId: s.simulationId } }
    if (s.argued || s.reportId) out[3] = { name: 'SimulationRun', params: { simulationId: s.simulationId } }
  }
  if (s.reportId) out[4] = { name: 'Report', params: { reportId: s.reportId } }
  if (s.written) out[5] = { name: 'Interaction', params: { reportId: s.reportId } }
  return out
}

// The route that opens a gathering where it stands: its Chronicle once there
// is one, else the Agora once it was argued, else the Gathering.
export const standingRoute = (row) => {
  const s = gatheringStanding(row)
  if (s.act >= 4 && s.reportId) return { name: 'Report', params: { reportId: s.reportId } }
  if (s.act >= 3 && s.simulationId) return { name: 'SimulationRun', params: { simulationId: s.simulationId } }
  if (s.simulationId) return { name: 'Simulation', params: { simulationId: s.simulationId } }
  return null
}
