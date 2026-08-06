import { createRouter, createWebHistory } from 'vue-router'

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
      { path: 'providers', name: 'providers', component: () => import('../views/Providers.vue') },
      { path: 'admin/config', name: 'admin-config', component: () => import('../views/AdminConfig.vue') }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫：无 token 重定向登录页
router.beforeEach((to) => {
  const token = localStorage.getItem('rag_token')
  if (!to.meta.public && !token) {
    return { path: '/login' }
  }
  if (to.meta.public && token) {
    return { path: '/chat' }
  }
  return true
})

export default router
