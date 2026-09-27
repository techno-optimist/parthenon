import axios from 'axios'
import i18n from '../i18n'
import { API_BASE } from '../parthenon/base.js'
import { OWNER_HEADER, OWNED_HEADER, ADMIN_HEADER, idsInRequest } from '../parthenon/owned.js'
import { access, cityCodeOf, inviteRefused, learnOwnership, noteResponseError, ownerTokenFor, shelfIds } from '../parthenon/access.js'
import { retryMinutes } from '../parthenon/limits.js'
import { INVITE_HEADER, isInvitedCall } from '../parthenon/invite.js'
import { markTicket, ticketOf } from '../parthenon/tickets.js'
import { readable } from '../parthenon/vocabulary.js'

// The engine's own words for a refusal, as the visitor can read them: its
// Chinese never reaches a reader of English (the page's own words stand in).
const inVisitorWords = (text) => readable(text, i18n.global.t('common.otherTongue'), i18n.global.locale.value)

// 创建axios实例
// The API sits under the page's base on the public steps ('/parthenon'), and
// at the local backend on the owner's own machine (see parthenon/base.js).
const service = axios.create({
  baseURL: API_BASE,
  timeout: 300000, // 5分钟超时（本体生成可能需要较长时间）
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
service.interceptors.request.use(
  config => {
    config.headers['Accept-Language'] = i18n.global.locale.value
    // A gathering this browser began: show its key, so the city lets it be steered.
    const token = ownerTokenFor(idsInRequest(config))
    if (token) {
      config.headers[OWNER_HEADER] = token
      config.parthenonOwner = token
    }
    if (access.admin) config.headers[ADMIN_HEADER] = access.admin
    // The word that opens the steps to speech, on the calls the city guards
    // with it (beginning a gathering, a question, the Oracle, making something
    // new). Never at home, where the city asks for none.
    if (access.invite && (access.public || access.inviteRequired) && isInvitedCall(config)) {
      config.headers[INVITE_HEADER] = access.invite
      config.parthenonInvite = access.invite
    }
    // The shelf on the public steps: the featured gatherings, and the ones this
    // browser knows (its own, and the one a link names).
    if (config.parthenonShelf && access.public) {
      const ids = shelfIds(config.parthenonShelf.ids || [])
      if (ids.length) config.headers[OWNED_HEADER] = ids.join(',')
    }
    return config
  },
  error => {
    console.error('Request error:', error)
    return Promise.reject(error)
  }
)

// 响应拦截器（容错重试机制）
service.interceptors.response.use(
  response => {
    const res = response.data
    // A gathering just begun hands back its key; a call about one this browser
    // began may name its later ids (the crowd, the Chronicle): keep them all.
    learnOwnership(response.config?.parthenonOwner || '', res)
    // A question on the public steps answered with a ticket (202): the caller
    // waits on it (api/tickets.js). At home the routes answer at once.
    if (ticketOf(response.status, res)) markTicket(res)
    // A ticket's own state is read whole by its waiter, whatever it says.
    if (response.config?.parthenonTicket) return res
    
    // 如果返回的状态码不是success，则抛出错误
    if (!res.success && res.success !== undefined) {
      console.error('API Error:', res.error || res.message || 'Unknown error')
      const failure = new Error(inVisitorWords(res.error || res.message || 'Error'))
      failure.engineMessage = res.error || res.message || ''
      return Promise.reject(failure)
    }
    
    return res
  },
  error => {
    // A limit or a closed door is the city answering, not a fault: noted quietly.
    noteResponseError(error)
    
    // 处理超时
    if (error.code === 'ECONNABORTED' && error.message.includes('timeout')) {
      console.error('Request timeout')
    }
    
    // 处理网络错误
    if (error.message === 'Network Error') {
      console.error('Network error - please check your connection')
    }

    return Promise.reject(explainRefusal(error))
  }
)

/**
 * A refused call in the city's words. Axios rejects non-2xx responses before
 * the success interceptor can surface the backend's safe, actionable error
 * message, so it is set here; a limit or a door on the public steps (429, 403,
 * 413) also carries its code, as error.cityCode (parthenon/access.js), and its
 * wait. The ticket waiter (api/tickets.js) reads a failed answer through here
 * too, so it reads exactly as the same refusal would have at once.
 */
export const explainRefusal = (error) => {
  const data = error?.response?.data
  const apiError = data?.error || data?.message
  if (typeof apiError === 'string' && apiError) {
    error.message = inVisitorWords(apiError)
    error.engineMessage = apiError
  }
  const code = cityCodeOf(data)
  if (code) {
    error.cityCode = code
    const retry = Number(data.retry_after_seconds ?? error.response.headers?.['retry-after'])
    if (Number.isFinite(retry) && retry > 0) error.retryAfter = retry
    if (!(typeof apiError === 'string' && apiError)) {
      error.message = i18n.global.t(`parthenon.public.codes.${code}`)
    }
    // A short wait (a seat in the Agora, a breath between questions) is named in minutes.
    const wait = retryMinutes(error.retryAfter)
    if (wait && wait <= 120 && (code === 'city_full' || code === 'slow_down')) {
      // Chinese sentences run on without a space between them.
      const gap = String(i18n.global.locale.value || '').startsWith('zh') ? '' : ' '
      error.message = `${error.message}${gap}${i18n.global.t('parthenon.public.retry', { n: wait }, wait)}`
    }
    // The city asks for the word: the one shown (if any) is not known.
    if (code === 'invite_needed') inviteRefused(error.config?.parthenonInvite || '')
  }
  return error
}

export default service
