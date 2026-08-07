<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="brand">RAG 知识问答</div>
      <div class="nav">
        <router-link to="/chat" class="nav-item">对话</router-link>
        <router-link to="/knowledge" class="nav-item">知识库</router-link>
        <router-link to="/faqs" class="nav-item">经验库</router-link>
        <router-link to="/providers" class="nav-item">模型供应商</router-link>
        <router-link v-if="userStore.isAdmin" to="/admin/config" class="nav-item">流水线配置</router-link>
        <router-link v-if="userStore.isAdmin" to="/users" class="nav-item">用户管理</router-link>
      </div>
      <el-dropdown @command="onCommand">
        <span class="user">
          {{ userStore.displayName }}
          <el-tag v-if="userStore.isAdmin" size="small" type="warning" effect="dark" style="margin-left: 6px">管理员</el-tag>
          <el-tag v-else-if="userStore.departmentName" size="small" type="info" effect="plain" style="margin-left: 6px">{{ userStore.departmentName }}</el-tag>
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </el-header>
    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()

onMounted(() => {
  if (userStore.token && !userStore.user) userStore.fetchMe().catch(() => {})
})

function onCommand(cmd) {
  if (cmd === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.header {
  display: flex;
  align-items: center;
  gap: 32px;
  background: #1f2d3d;
  color: #fff;
}
.brand {
  font-size: 18px;
  font-weight: 600;
}
.nav {
  display: flex;
  gap: 8px;
  flex: 1;
}
.nav-item {
  color: #cfd8e3;
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 14px;
  text-decoration: none;
}
.nav-item.router-link-active,
.nav-item:hover {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}
.user {
  color: #fff;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}
.main {
  padding: 0;
  background: #f5f7fa;
  overflow: hidden;
}
</style>
