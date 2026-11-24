import http from './http'

export interface ReviewTask {
  id: number
  contract_id: number
  contract_name: string
  thread_id: string
  status: string
  current_node: string
  error_msg: string
  create_time: string
  finish_time: string | null
}

export interface QueueTask extends ReviewTask {
  risk_total: number
  high_count: number
  medium_count: number
}

export interface Clause {
  id: number
  clause_no: string
  title: string
  clause_type: string
  content: string
  confidence: number
}

export interface Suggestion {
  id: number
  suggest_text: string
  reason: string
  reference: string
}

export interface Risk {
  id: number
  clause_id: number | null
  level: 'high' | 'medium' | 'low'
  risk_type: string
  description: string
  evidence: string
  confidence: number
  handle_status: string
  suggestion: Suggestion | null
}

export interface TaskDetail {
  task: ReviewTask
  clauses: Clause[]
  risks: Risk[]
}

export interface FeedbackAction {
  suggestion_id?: number
  risk_id?: number
  action: 'accept' | 'reject' | 'edit'
  edited_text?: string
  comment?: string
}

export const reviewApi = {
  upload: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return http.post('/contract/upload', form)
  },
  start: (taskId: number) => http.post(`/review/${taskId}/start`),
  list: () => http.get<{ code: number; data: ReviewTask[] }>('/review/list'),
  queue: () => http.get<{ code: number; data: QueueTask[] }>('/review/queue'),
  detail: (taskId: number) => http.get<{ code: number; data: TaskDetail }>(`/review/${taskId}/detail`),
  feedback: (taskId: number, actions: FeedbackAction[]) =>
    http.post(`/review/${taskId}/feedback`, { actions }),
  reportUrl: (taskId: number) => `/api/review/${taskId}/report?token=${localStorage.getItem('token')}`,
  exportUrl: (taskId: number, format: 'docx' | 'txt' = 'docx') =>
    `/api/review/${taskId}/report/export?format=${format}&token=${localStorage.getItem('token')}`,
}
