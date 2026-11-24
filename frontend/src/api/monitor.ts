import http from './http'

export interface MonitorOverview {
  services: Record<string, string>
  workers: number
  queue_length: number
  tasks: {
    status_counts: Record<string, number>
    running: number
    pending_audit: number
    done_24h: number
    failed_24h: number
    failure_rate: number
  }
  recent_failures: {
    task_id: number
    contract_name: string
    error_msg: string
    finish_time: string | null
  }[]
  checked_at: string
}

export const monitorApi = {
  overview: () => http.get<{ code: number; data: MonitorOverview }>('/monitor/overview'),
}
