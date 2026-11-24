import http from './http'

export interface AuditItem {
  id: number
  operator_id: number | null
  operator: string
  real_name: string
  action: string
  target: string
  detail: string
  create_time: string
}

export interface AuditQuery {
  page: number
  page_size: number
  action?: string
  operator?: string
  keyword?: string
  start?: string
  end?: string
}

export interface AuditPage {
  items: AuditItem[]
  total: number
  page: number
  page_size: number
}

export const auditApi = {
  logs: (params: AuditQuery) => http.get<{ code: number; data: AuditPage }>('/audit/logs', { params }),
  actions: () => http.get<{ code: number; data: string[] }>('/audit/actions'),
}
