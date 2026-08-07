<template>
  <div class="auth-wrap">
    <el-card class="auth-card">
      <h2 class="title">注册账号</h2>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="submit">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="3-32 位用户名" />
        </el-form-item>
        <el-form-item label="昵称（可选）" prop="nickname">
          <el-input v-model="form.nickname" placeholder="显示名称" />
        </el-form-item>
        <el-form-item label="申请加入部门（可选，需管理员审批）" prop="department_id">
          <el-select v-model="form.department_id" placeholder="暂不加入部门" clearable style="width: 100%">
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id">
              <span>{{ d.name }}</span>
              <span v-if="d.description" style="color: #909399; font-size: 12px; margin-left: 8px">{{ d.description }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-button type="primary" class="w-full" :loading="loading" @click="submit">注 册</el-button>
      </el-form>
      <div class="foot">
        已有账号？
        <router-link to="/login">去登录</router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { register } from '../api/auth'
import { listPublicDepartments } from '../api/admin'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()
const formRef = ref()
const loading = ref(false)
const departments = ref([])
const form = reactive({ username: '', password: '', nickname: '', department_id: null })

onMounted(async () => {
  try {
    departments.value = await listPublicDepartments()
  } catch (e) {
    departments.value = []
  }
})
const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '长度 3-32 位', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '至少 6 位', trigger: 'blur' },
  ],
}

async function submit() {
  await formRef.value.validate()
  loading.value = true
  try {
    const res = await register(form)
    userStore.setAuth(res.token, res.user)
    ElMessage.success(form.department_id ? '注册成功，部门申请已提交待审批' : '注册成功，已自动登录')
    router.push('/chat')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.auth-wrap {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #2b4a6f 100%);
}
.auth-card {
  width: 380px;
  border-radius: 12px;
}
.title {
  text-align: center;
  margin: 8px 0 20px;
  font-size: 22px;
}
.w-full {
  width: 100%;
}
.foot {
  margin-top: 14px;
  text-align: center;
  font-size: 13px;
  color: #909399;
}
</style>
