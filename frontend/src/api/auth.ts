import http from './http'

export interface LoginResult {
  token: string
  username: string
  real_name: string
  permissions: string[]
}

export const authApi = {
  login: (username: string, password: string) =>
    http.post<{ code: number; data: LoginResult }>('/auth/login', { username, password }),
}
