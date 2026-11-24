import { defineStore } from 'pinia'
import { authApi } from '../api/auth'

// 全局用户状态：登录后保存 token 与权限码
export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('token') ?? '',
    username: localStorage.getItem('username') ?? '',
    realName: localStorage.getItem('realName') ?? '',
    permissions: JSON.parse(localStorage.getItem('permissions') ?? '[]') as string[],
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
  },
  actions: {
    async login(username: string, password: string) {
      const { data } = await authApi.login(username, password)
      const d = data.data
      this.token = d.token
      this.username = d.username
      this.realName = d.real_name
      this.permissions = d.permissions
      localStorage.setItem('token', d.token)
      localStorage.setItem('username', d.username)
      localStorage.setItem('realName', d.real_name)
      localStorage.setItem('permissions', JSON.stringify(d.permissions))
    },
    logout() {
      this.token = ''
      this.username = ''
      this.realName = ''
      this.permissions = []
      localStorage.clear()
    },
    hasPerm(code: string) {
      return this.permissions.includes(code)
    },
  },
})
