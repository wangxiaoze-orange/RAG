import { defineStore } from 'pinia'
import { listProviders } from '../api/provider'

export const useProviderStore = defineStore('provider', {
  state: () => ({
    list: [],
    loading: false,
  }),
  getters: {
    defaultProvider: (s) => s.list.find((p) => p.is_default) || s.list[0] || null,
  },
  actions: {
    async fetch() {
      this.loading = true
      try {
        this.list = await listProviders()
      } finally {
        this.loading = false
      }
    },
  },
})
