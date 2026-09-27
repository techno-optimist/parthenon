// How the Symposium asks and reads answers. Pure; no Vue, so node can test it.
// A live citizen hears the conversation folded into one prompt, as always; a
// citizen answering from memory (once the square has closed) also gets the
// question and the recent turns apart, so the backend can hold them straight.

export const MEMORY_HISTORY_TURNS = 6

// The prompt the live city has always been sent, byte for byte, plus the
// question and the clean recent turns for an answer from memory.
export const conversationFor = (prior, message, turns = MEMORY_HISTORY_TURNS) => {
  const lines = Array.isArray(prior) ? prior : []
  const prompt = lines.length > 0
    ? `Earlier in our conversation:\n${lines.slice(-6).map((m) => `${m.role === 'user' ? 'Questioner' : 'You'}: ${m.content}`).join('\n')}\n\nNow my next question is: ${message}`
    : message
  const history = lines
    .filter((m) => m && !m.failed && (m.role === 'user' || m.role === 'assistant') && String(m.content || '').trim())
    .slice(-turns)
    .map((m) => ({ role: m.role, content: String(m.content) }))
  return { prompt, question: message, history }
}

// One citizen's answer out of an interview reply, live or remembered.
// Replies come keyed by square and seat ({ reddit_0: {...}, twitter_0: {...} }) or as a list.
export const answerFrom = (data, idx, { anyFallback = false } = {}) => {
  const resultData = data?.result || data || {}
  const dict = resultData.results || resultData.platforms || resultData
  let entry = null
  if (Array.isArray(dict)) {
    entry = dict.find((r) => r && r.agent_id === idx) || (anyFallback ? dict[0] : null) || null
  } else if (dict && typeof dict === 'object') {
    entry = dict[`reddit_${idx}`] || dict[`twitter_${idx}`] || dict.reddit || dict.twitter || null
    if (!entry && anyFallback) entry = Object.values(dict).find((v) => v && typeof v === 'object' && !Array.isArray(v)) || null
  }
  const text = String(entry?.response || entry?.answer || '')
  const remembered = entry?.from_memory === true || resultData.from_memory === true || data?.from_memory === true
  const memory = !!text && remembered
  // Only a remembered entry's error is already in the city's words; a live
  // entry's error is engine text (a platform, a raw exception) and is never shown.
  const error = remembered && typeof entry?.error === 'string' ? entry.error : ''
  return { text, memory, error }
}

// An error whose words are already the city's own, safe to show as they are.
export const cityError = (message) => Object.assign(new Error(String(message || '')), { cityWords: true })

// The only way the Symposium turns an error into words a visitor reads: the
// page's own words, a remembered answer's own error, or the fallback. Engine
// text (a closed environment, a raw exception) never reaches the room.
export const troubleFrom = (err, fallback) => {
  if (err?.cityWords) return err.message
  const data = err?.response?.data
  if (data?.from_memory === true && typeof data.error === 'string' && data.error.trim()) return data.error
  return fallback
}

// Whether the citizens can be asked: always while the city is awake (or not yet
// known), and once it sleeps only when they can answer from memory.
export const canQuestion = (cityState, memoryReady) => cityState !== 'asleep' || memoryReady === true
export const isRemembering = (cityState, memoryReady) => cityState === 'asleep' && memoryReady === true
