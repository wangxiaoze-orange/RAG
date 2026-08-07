<template>
  <div class="user-page">
    <el-tabs v-model="tab" @tab-change="onTabChange">
      <!-- ============ 用户管理 ============ -->
      <el-tab-pane label="用户管理" name="users">
        <div class="toolbar">
          <el-input v-model="keyword" placeholder="搜索用户名/昵称" clearable style="width: 240px" @keyup.enter="loadUsers" @clear="loadUsers" />
          <el-button type="primary" @click="loadUsers">搜索</el-button>
        </div>
        <el-table :data="users" v-loading="usersLoading" stripe>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="username" label="用户名" width="150" />
          <el-table-column prop="nickname" label="昵称" width="150">
            <template #default="{ row }">{{ row.nickname || '—' }}</template>
          </el-table-column>
          <el-table-column label="角色" width="140">
            <template #default="{ row }">
              <el-select :model-value="row.role" size="small" style="width: 110px" :disabled="row.id === me.id" @change="(v) => changeRole(row, v)">
                <el-option label="管理员" value="admin" />
                <el-option label="普通用户" value="user" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="部门" min-width="180">
            <template #default="{ row }">
              <el-select :model-value="row.department_id" size="small" clearable placeholder="未加入" style="width: 150px" @change="(v) => changeDept(row, v)">
                <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="120">
            <template #default="{ row }">
              <el-tag :type="row.status === 1 ? 'success' : 'danger'" size="small">{{ row.status === 1 ? '正常' : '已禁用' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120">
            <template #default="{ row }">
              <el-button v-if="row.status === 1" size="small" type="danger" plain :disabled="row.id === me.id" @click="toggleStatus(row, 0)">禁用</el-button>
              <el-button v-else size="small" type="success" plain @click="toggleStatus(row, 1)">启用</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============ 部门管理 ============ -->
      <el-tab-pane label="部门管理" name="depts">
        <div class="toolbar">
          <el-button type="primary" @click="openDeptDialog(null)">
            <el-icon><Plus /></el-icon>&nbsp;新建部门
          </el-button>
        </div>
        <el-table :data="departments" v-loading="deptsLoading" stripe>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="name" label="名称" width="180" />
          <el-table-column prop="description" label="描述" min-width="240">
            <template #default="{ row }">{{ row.description || '—' }}</template>
          </el-table-column>
          <el-table-column prop="member_count" label="成员数" width="90" />
          <el-table-column prop="pending_count" label="待审批" width="90">
            <template #default="{ row }">
              <el-tag v-if="row.pending_count" size="small" type="warning">{{ row.pending_count }}</el-tag>
              <span v-else>0</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="160">
            <template #default="{ row }">
              <el-button size="small" @click="openDeptDialog(row)">编辑</el-button>
              <el-button size="small" type="danger" plain @click="removeDept(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ============ 入部审批 ============ -->
      <el-tab-pane label="入部审批" name="apply">
        <div class="toolbar">
          <el-radio-group v-model="applyFilter" @change="loadApplies">
            <el-radio-button value="pending">待审批</el-radio-button>
            <el-radio-button value="approved">已通过</el-radio-button>
            <el-radio-button value="rejected">已驳回</el-radio-button>
            <el-radio-button value="all">全部</el-radio-button>
          </el-radio-group>
        </div>
        <el-table :data="applies" v-loading="appliesLoading" stripe>
          <el-table-column prop="username" label="申请人" width="150" />
          <el-table-column prop="nickname" label="昵称" width="150">
            <template #default="{ row }">{{ row.nickname || '—' }}</template>
          </el-table-column>
          <el-table-column prop="department_name" label="申请部门" width="160" />
          <el-table-column label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="{ pending: 'warning', approved: 'success', rejected: 'danger' }[row.status]">
                {{ { pending: '待审批', approved: '已通过', rejected: '已驳回' }[row.status] }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="created_at" label="申请时间" min-width="180">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <template v-if="row.status === 'pending'">
                <el-button size="small" type="success" @click="doApprove(row)">通过</el-button>
                <el-button size="small" type="danger" plain @click="doReject(row)">驳回</el-button>
              </template>
              <span v-else class="muted">已处理</span>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <!-- 新建/编辑部门 -->
    <el-dialog v-model="deptVisible" :title="deptForm.id ? '编辑部门' : '新建部门'" width="420px">
      <el-form label-width="60px">
        <el-form-item label="名称">
          <el-input v-model="deptForm.name" maxlength="64" placeholder="部门名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="deptForm.description" type="textarea" :rows="2" maxlength="256" placeholder="部门职责说明（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deptVisible = false">取消</el-button>
        <el-button type="primary" @click="submitDept">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '../stores/user'
import {
  listUsers, setUserStatus, setUserRole, setUserDepartment,
  listDepartments, createDepartment, updateDepartment, deleteDepartment,
  listApplications, approveApplication, rejectApplication,
} from '../api/admin'

const userStore = useUserStore()
const me = userStore.user || {}

const tab = ref('users')
const keyword = ref('')
const users = ref([])
const usersLoading = ref(false)
const departments = ref([])
const deptsLoading = ref(false)
const applies = ref([])
const appliesLoading = ref(false)
const applyFilter = ref('pending')
const deptVisible = ref(false)
const deptForm = reactive({ id: null, name: '', description: '' })

onMounted(() => {
  loadUsers()
  loadDepts()
})

function fmtTime(s) {
  return s ? new Date(s).toLocaleString() : '—'
}

async function loadUsers() {
  usersLoading.value = true
  try {
    users.value = await listUsers({ keyword: keyword.value })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    usersLoading.value = false
  }
}

async function loadDepts() {
  deptsLoading.value = true
  try {
    departments.value = await listDepartments()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    deptsLoading.value = false
  }
}

async function loadApplies() {
  appliesLoading.value = true
  try {
    applies.value = await listApplications(applyFilter.value)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    appliesLoading.value = false
  }
}

function onTabChange(name) {
  if (name === 'users') loadUsers()
  else if (name === 'depts') loadDepts()
  else loadApplies()
}

async function toggleStatus(row, status) {
  try {
    await setUserStatus(row.id, status)
    ElMessage.success(status === 1 ? '已启用' : '已禁用')
    loadUsers()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function changeRole(row, role) {
  try {
    await setUserRole(row.id, role)
    ElMessage.success('角色已更新')
    loadUsers()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function changeDept(row, deptId) {
  try {
    await setUserDepartment(row.id, deptId || null)
    ElMessage.success('部门已更新')
    loadUsers()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

function openDeptDialog(row) {
  deptForm.id = row?.id || null
  deptForm.name = row?.name || ''
  deptForm.description = row?.description || ''
  deptVisible.value = true
}

async function submitDept() {
  if (!deptForm.name.trim()) return ElMessage.warning('请输入部门名称')
  try {
    const data = { name: deptForm.name, description: deptForm.description || null }
    if (deptForm.id) await updateDepartment(deptForm.id, data)
    else await createDepartment(data)
    ElMessage.success('保存成功')
    deptVisible.value = false
    loadDepts()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function removeDept(row) {
  try {
    await ElMessageBox.confirm(`删除部门「${row.name}」？其知识库授权与待审申请将一并清除`, '危险操作', { type: 'warning' })
    await deleteDepartment(row.id)
    ElMessage.success('已删除')
    loadDepts()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}

async function doApprove(row) {
  try {
    await approveApplication(row.id)
    ElMessage.success(`已通过 ${row.username} 加入「${row.department_name}」`)
    loadApplies()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function doReject(row) {
  try {
    await rejectApplication(row.id)
    ElMessage.success('已驳回')
    loadApplies()
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.user-page {
  padding: 20px;
  height: 100%;
  overflow-y: auto;
}
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.muted {
  color: #909399;
  font-size: 12px;
}
</style>
