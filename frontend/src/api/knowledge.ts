import http from './http'

export interface KnowledgeDoc {
  id: number
  lib_type: string
  title: string
  vector_status: string
  create_time: string
}

export interface KnowledgeHit {
  score: number
  content: string
  doc_id?: number
  title?: string
  rule_id?: number
  code?: string
  name?: string
  version?: number
}

export const knowledgeApi = {
  list: (libType: string) =>
    http.get<{ code: number; data: KnowledgeDoc[] }>('/knowledge/list', { params: { lib_type: libType } }),
  upload: (file: File, libType: string) => {
    const form = new FormData()
    form.append('file', file)
    return http.post<{ code: number; data: KnowledgeDoc & { chunk_count: number } }>(
      '/knowledge/upload', form, { params: { lib_type: libType }, timeout: 120000 },
    )
  },
  search: (q: string, libType: string, topK: number) =>
    http.get<{ code: number; data: { query: string; lib_type: string; hits: KnowledgeHit[] } }>(
      '/knowledge/search', { params: { q, lib_type: libType, top_k: topK }, timeout: 60000 },
    ),
}
