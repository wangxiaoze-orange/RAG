import http from './http'

export const listConversations = () => http.get('/conversations')
export const listMessages = (convId) => http.get(`/conversations/${convId}/messages`)
export const deleteConversation = (convId) => http.delete(`/conversations/${convId}`)
