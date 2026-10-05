// Browser SpeechRecognition is optional. Nothing requests a microphone until
// start() is invoked by an explicit user action; no server STT is implied.
export function createDictation({ Recognition, secure = false, onText = () => {}, onStatus = () => {}, onError = () => {} } = {}) {
  const supported = secure === true && typeof Recognition === 'function'
  let recognition = null, active = false, generation = 0
  function start(lang = 'en-US') {
    if (!supported || active) return false
    const ownGeneration = ++generation
    const delivered = new Set()
    try {
      recognition = new Recognition()
      recognition.lang = lang
      recognition.interimResults = false
      recognition.continuous = false
      recognition.onstart = () => { if (ownGeneration === generation) onStatus('listening') }
      recognition.onresult = event => {
        if (ownGeneration !== generation) return
        for (let i = event.resultIndex || 0; i < event.results.length; i++) {
          const result = event.results[i]
          if (result.isFinal && !delivered.has(i)) {
            delivered.add(i)
            const text = String(result[0]?.transcript || '').trim()
            if (text) onText(text)
          }
        }
      }
      recognition.onerror = event => {
        if (ownGeneration !== generation) return
        active = false
        onError(String(event.error || 'unknown'))
        onStatus('idle')
      }
      recognition.onend = () => {
        if (ownGeneration !== generation) return
        active = false; onStatus('idle')
      }
      active = true; onStatus('starting')
      recognition.start()
      return true
    } catch {
      active = false; onStatus('idle'); onError('start-failed')
      return false
    }
  }
  function stop() {
    if (!active || !recognition) return
    onStatus('stopping')
    try { recognition.stop() } catch { active = false; onStatus('idle') }
  }
  function dispose() {
    generation++
    active = false
    try { recognition?.abort() } catch { /* Browser already ended. */ }
    recognition = null
    onStatus('idle')
  }
  return { supported, start, stop, dispose }
}
