import http from './http'

export const listKbs = () => http.get('/kb')
export const createKb = (data) => http.post('/kb', data)
export const updateKb = (id, data) => http.put(`/kb/${id}`, data)
export const deleteKb = (id) => http.delete(`/kb/${id}`)

export const listDocuments = (kbId) => http.get(`/kb/${kbId}/documents`)
export const uploadDocument = (kbId, file, onProgress) => {
  const fd = new FormData()
  fd.append('file', file)
  return http.post(`/kb/${kbId}/documents`, fd, {
    onUploadProgress: onProgress,
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const deleteDocument = (docId) => http.delete(`/documents/${docId}`)
export const retryDocument = (docId) => http.post(`/documents/${docId}/retry`)
export const listChunks = (kbId, params) => http.get(`/kb/${kbId}/chunks`, { params })
export const getKbDepartments = (kbId) => http.get(`/kb/${kbId}/departments`)
export const setKbDepartments = (kbId, department_ids) => http.put(`/kb/${kbId}/departments`, { department_ids })
