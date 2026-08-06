import http from './http'

export const listProviders = () => http.get('/providers')
export const createProvider = (data) => http.post('/providers', data)
export const updateProvider = (name, data) => http.put(`/providers/${name}`, data)
export const deleteProvider = (name) => http.delete(`/providers/${name}`)
export const setDefaultProvider = (name) => http.post(`/providers/${name}/default`)
export const testProvider = (name, data) => http.post(`/providers/${name}/test`, data)
