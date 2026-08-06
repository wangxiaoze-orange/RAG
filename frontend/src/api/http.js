import axios from 'axios'

const http = axios.create({
  baseURL: '/api/v2',
  timeout: 60000,
})

// 请求：自动带 JWT
http.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('rag_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// 响应：直接吐 data；401 清 token 跳登录；其余归一为 Error
http.interceptors.response.use(
  (resp) => resp.data,
  (err) => {
    if (err.response?.status === 401 && !location.pathname.startsWith('/login')) {
      localStorage.removeItem('rag_token')
      location.href = '/login'
    }
    const detail = err.response?.data?.detail
    return Promise.reject(new Error(detail || err.message || '请求失败'))
  },
)

export default http
