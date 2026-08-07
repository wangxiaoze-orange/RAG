import http from './http'

// ============ 部门 ============
export const listPublicDepartments = () => http.get('/departments/public')
export const listDepartments = () => http.get('/admin/departments')
export const createDepartment = (data) => http.post('/admin/departments', data)
export const updateDepartment = (id, data) => http.put(`/admin/departments/${id}`, data)
export const deleteDepartment = (id) => http.delete(`/admin/departments/${id}`)

// ============ 用户 ============
export const listUsers = (params) => http.get('/admin/users', { params })
export const setUserStatus = (id, status) => http.put(`/admin/users/${id}/status`, { status })
export const setUserRole = (id, role) => http.put(`/admin/users/${id}/role`, { role })
export const setUserDepartment = (id, department_id) => http.put(`/admin/users/${id}/department`, { department_id })

// ============ 入部申请 ============
export const listApplications = (status = 'pending') => http.get('/admin/applications', { params: { status } })
export const approveApplication = (id) => http.post(`/admin/applications/${id}/approve`)
export const rejectApplication = (id) => http.post(`/admin/applications/${id}/reject`)
export const myDepartment = () => http.get('/my-department')

// ============ 经验库 FAQ ============
export const listFaqs = (params) => http.get('/faqs', { params })
export const updateFaq = (id, data) => http.put(`/faqs/${id}`, data)
export const publishFaq = (id) => http.post(`/faqs/${id}/publish`)
export const disableFaq = (id) => http.post(`/faqs/${id}/disable`)
export const deleteFaq = (id) => http.delete(`/faqs/${id}`)
export const searchFaqs = (q) => http.get('/faqs/search', { params: { q } })

// ============ 流水线配置 ============
export const getConfig = () => http.get('/admin/config')
export const setConfig = (values) => http.put('/admin/config', { values })
