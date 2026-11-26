import { request } from './client'

export type ApiResult<T = unknown> = {
  ok: boolean
  message: string
  data?: T
}

async function postJson<T = unknown>(path: string, body: Record<string, unknown> = {}): Promise<ApiResult<T>> {
  const response = await request(path, { method: 'POST', body: JSON.stringify(body) })
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return (await response.json()) as ApiResult<T>
}

async function getJson<T = unknown>(path: string): Promise<ApiResult<T>> {
  const response = await request(path)
  if (!response.ok) throw new Error(`接口返回 ${response.status}`)
  return (await response.json()) as ApiResult<T>
}

// ---- 报告分发 ----

export type ContinuationItem = {
  id: number
  分发批次: string
  报告版次: string
  报告编码: string
  接收方: string
  分发渠道: string
  当前状态: string
  失败原因: string
  续做次数: string
  本人地址有效: boolean
  生效代领资格: string
  可代领人: string
}

export type ContinuationData = {
  报告版次: string
  待续做人数: number
  items: ContinuationItem[]
}

export type Receipt = {
  id: number
  回执编号: string
  报告版次: string
  报告编码: string
  分发批次: string
  接收方: string
  分发渠道: string
  实际签收人: string
  使用代领资格: string
  是否代领: boolean
  签收状态: string
  送达时间: string
}

export type Proxy = {
  id: number
  资格编号: string
  报告版次: string
  接收方: string
  代领人: string
  资格状态: string
  登记时间: string
  撤换时间: string
  使用时间: string
  使用回执: string
}

export type DeliveryDetail = {
  entry: Record<string, string | number | boolean>
  可续办: boolean
  未送达区: {
    当前状态: string
    失败原因: string
    本人地址有效: boolean
    续做次数: string
    续做意向: string
    生效代领资格: string
    可代领人: string
  } | null
  已签收区: Receipt[]
  代领资格沿革: Proxy[]
}

export function fetchContinuationList(version = '', batchId = '') {
  const query = new URLSearchParams()
  if (version) query.set('report_version', version)
  if (batchId) query.set('batch_id', batchId)
  return getJson<ContinuationData>(`/api/report_dist/continuation?${query.toString()}`)
}

export function registerContinuation(entryId: number, preferProxy = false) {
  return postJson(`/api/report_dist/${entryId}/continuation`, { prefer_proxy: preferProxy })
}

export function rejectReceived(entryId: number, reason: string) {
  return postJson(`/api/report_dist/${entryId}/reject`, { reason })
}

export function switchChannel(entryId: number, channel: string) {
  return postJson(`/api/report_dist/${entryId}/channel`, { channel })
}

export function deliverEntry(entryId: number, useProxy: boolean | null) {
  return postJson(`/api/report_dist/${entryId}/deliver`, { use_proxy: useProxy })
}

export function batchDeliver(entryIds: number[]) {
  return postJson('/api/report_dist/batch-deliver', { entry_ids: entryIds })
}

export function fetchDeliveryDetail(entryId: number) {
  return getJson<DeliveryDetail>(`/api/report_dist/${entryId}/detail`)
}

export function fetchProxies(version = '') {
  const query = new URLSearchParams()
  if (version) query.set('report_version', version)
  return getJson<Proxy[]>(`/api/report_dist/proxy/active?${query.toString()}`)
}

export function registerProxy(payload: {
  report_version: string
  receiver: string
  proxy_person: string
  replace: boolean
}) {
  return postJson('/api/report_dist/proxy', payload)
}

export function fetchValidReceipts(version = '', receiver = '') {
  const query = new URLSearchParams()
  if (version) query.set('report_version', version)
  if (receiver) query.set('receiver', receiver)
  return getJson<Receipt[]>(`/api/report_dist/receipts/valid?${query.toString()}`)
}

// ---- 结论评审 ----

export type VersionEvidence = {
  报告版次: string
  报告编码: string
  有效签收数: number
  实际送达的人: Receipt[]
  投递批次: string[]
}

export type AvailableEvidence = {
  报告版次: string
  可领用: boolean
  message: string
  items: Receipt[]
}

export type ReviewEvidenceDetail = {
  记录编号: string
  评审状态: string
  按版次证据: { 报告版次: string; 实际送达的人: Array<Record<string, string | boolean>> }[]
}

export function fetchEvidenceVersions(reportCode = '') {
  const query = new URLSearchParams()
  if (reportCode) query.set('report_code', reportCode)
  return getJson<VersionEvidence[]>(`/api/conclusion_review/evidence/versions?${query.toString()}`)
}

export function fetchAvailableEvidence(version: string) {
  return getJson<AvailableEvidence>(
    `/api/conclusion_review/evidence/available?report_version=${encodeURIComponent(version)}`,
  )
}

export function claimEvidence(entryId: number, payload: {
  report_version: string
  receipt_id: number
  reviewer: string
}) {
  return postJson(`/api/conclusion_review/${entryId}/claim`, payload)
}

export function fetchReviewEvidence(entryId: number) {
  return getJson<ReviewEvidenceDetail>(`/api/conclusion_review/${entryId}/evidence`)
}

export function approveReview(entryId: number, comment: string) {
  return postJson(`/api/conclusion_review/${entryId}/approve`, { comment })
}
