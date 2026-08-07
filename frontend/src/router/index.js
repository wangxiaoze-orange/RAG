import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '../stores/user'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/register', name: 'register', component: () => import('../views/Register.vue'), meta: { public: true } },
  {
    path: '/',
    component: () => import('../layouts/MainLayout.vue'),
    children: [
      { path: '', redirect: '/chat' },
      { path: 'chat', name: 'chat', component: () => import('../views/Chat.vue') },
      { path: 'knowledge', name: 'knowledge', component: () => import('../views/KnowledgeBase.vue') },
      { path: 'faqs', name: 'faqs', component: () => import('../views/FaqManage.vue') },
      { path: 'providers', name: 'providers', component: () => import('../views/Providers.vue') },
      { path: 'admin/config', name: 'admin-config', component: () => import('../views/AdminConfig.vue'), meta: { admin: true } },
      { path: 'users', name: 'users', component: () => import('../views/UserManage.vue'), meta: { admin: true } },
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫：无 token 重定向登录页；admin 页面需管理员角色
router.beforeEach(async (to) => {
  const token = localStorage.getItem('rag_token')
  if (!to.meta.public && !token) {
    return { path: '/login' }
  }
  if (to.meta.public && token) {
    return { path: '/chat' }
  }
  if (to.meta.admin && token) {
    const userStore = useUserStore()
    if (!userStore.user) {
      try {
        await userStore.fetchMe()
      } catch (e) {
        return { path: '/chat' }
      }
    }
    if (!userStore.isAdmin) {
      return { path: '/chat' }
    }
  }
  return true
})

export default router
