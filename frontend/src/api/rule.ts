import http from './http'

export interface RuleItem {
  id: number
  code: string
  name: string
  group_name: string
  version: number
  status: number
  content: string
  vector_status: string
  create_time: string
}

export interface RuleCreateBody {
  code: string
  name: string
  group_name: string
  content: string
  status: number
}

export interface RuleUpdateBody {
  name?: string
  group_name?: string
  content?: string
  status?: number
}

type RuleResp = { code: number; message: string; data: RuleItem }

export const ruleApi = {
  list: () => http.get<{ code: number; data: RuleItem[] }>('/rule'),
  create: (body: RuleCreateBody) => http.post<RuleResp>('/rule', body),
  update: (id: number, body: RuleUpdateBody) => http.put<RuleResp>(`/rule/${id}`, body),
  remove: (id: number) => http.delete<{ code: number; data: { deleted: number } }>(`/rule/${id}`),
}
