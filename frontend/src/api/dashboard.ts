import http from './http'

export interface DashboardSummary {
  total_tasks: number
  done_tasks: number
  pending_audit: number
  failed_tasks: number
  running_tasks: number
  total_risks: number
  high_risks: number
  medium_risks: number
  low_risks: number
  avg_duration_minutes: number
  accept_rate: number
  revision_count: number
}

export interface TrendPoint {
  date: string
  created: number
  completed: number
  avg_minutes: number
}

export interface NameValue {
  name: string
  value: number
  key?: string
}

export interface DashboardOverview {
  period_days: number
  summary: DashboardSummary
  trend: TrendPoint[]
  risk_levels: NameValue[]
  risk_types: NameValue[]
  status_distribution: NameValue[]
  handle_distribution: NameValue[]
}

export const dashboardApi = {
  overview: (days = 14) =>
    http.get<{ code: number; data: DashboardOverview }>('/dashboard/overview', { params: { days } }),
}
