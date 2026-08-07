import { defineStore } from 'pinia'
import { me } from '../api/auth'

export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('rag_token') || '',
    user: null,
  }),
  getters: {
    isLoggedIn: (s) => !!s.token,
    displayName: (s) => s.user?.nickname || s.user?.username || '',
    isAdmin: (s) => s.user?.role === 'admin',
    departmentName: (s) => s.user?.department_name || '',
  },
  actions: {
    setAuth(token, user) {
      this.token = token
      this.user = user
      localStorage.setItem('rag_token', token)
    },
    async fetchMe() {
      this.user = await me()
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('rag_token')
    },
  },
})
