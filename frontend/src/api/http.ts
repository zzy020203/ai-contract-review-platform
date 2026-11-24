import axios from 'axios'

// 统一 Axios 实例：后续在拦截器中注入 JWT、统一错误处理
const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export default http
