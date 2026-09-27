import service from './index'
import { asked } from './tickets'

/**
 * 开始报告生成
 * @param {Object} data - { simulation_id, force_regenerate? }
 */
export const generateReport = (data) => {
  return service.post('/api/report/generate', data)
}

/**
 * 获取报告生成状态
 * @param {string} reportId
 */
export const getReportStatus = (reportId) => {
  return service.get(`/api/report/generate/status`, { params: { report_id: reportId } })
}

/**
 * 获取 Agent 日志（增量）
 * @param {string} reportId
 * @param {number} fromLine - 从第几行开始获取
 */
export const getAgentLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/agent-log`, { params: { from_line: fromLine } })
}

/**
 * 获取控制台日志（增量）
 * @param {string} reportId
 * @param {number} fromLine - 从第几行开始获取
 */
export const getConsoleLog = (reportId, fromLine = 0) => {
  return service.get(`/api/report/${reportId}/console-log`, { params: { from_line: fromLine } })
}

/**
 * The newest Chronicle of one run, however it stands.
 * @param {string} simulationId
 * @returns {Promise<{ success: true, data: { report_id: string, status: string, error?: string } }>}
 */
export const getReportBySimulation = (simulationId) => {
  return service.get(`/api/report/by-simulation/${simulationId}`)
}

/**
 * 获取报告详情
 * @param {string} reportId
 */
export const getReport = (reportId) => {
  return service.get(`/api/report/${reportId}`)
}

/**
 * 与 Report Agent 对话
 * @param {Object} data - { simulation_id, message, chat_history? }
 * @param {{ signal?: AbortSignal }} [options] - on the public steps the answer
 *   may come as a ticket, waited for (api/tickets.js); abort to stop waiting
 */
export const chatWithReport = (data, options) => {
  return asked(service.post('/api/report/chat', data), options)
}
