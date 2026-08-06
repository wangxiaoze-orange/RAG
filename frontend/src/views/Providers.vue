<template>
  <div class="providers-page">
    <div class="head">
      <h3>模型供应商</h3>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>&nbsp;新增供应商
      </el-button>
    </div>

    <el-alert
      v-if="!list.length"
      title="尚未配置供应商。先新增一个（如硅基流动 siliconflow），设为默认后即可开始对话。"
      type="warning"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <el-table :data="list" v-loading="loading" stripe>
      <el-table-column label="名称" prop="name" width="130">
        <template #default="{ row }">
          <el-tag v-if="row.is_default" type="success" size="small" style="margin-right: 4px">默认</el-tag>
          {{ row.name }}
        </template>
      </el-table-column>
      <el-table-column label="类型" prop="provider_type" width="110" />
      <el-table-column label="Base URL" prop="base_url" min-width="220" show-overflow-tooltip />
      <el-table-column label="对话模型" prop="model" width="150" show-overflow-tooltip />
      <el-table-column label="嵌入模型" width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.embedding_model || '—' }}</template>
      </el-table-column>
      <el-table-column label="重排模型" width="170" show-overflow-tooltip>
        <template #default="{ row }">{{ row.rerank_model || '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.enabled ? 'success' : 'info'" size="small">{{ row.enabled ? '启用' : '停用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="test(row)">测试</el-button>
          <el-button size="small" type="warning" plain @click="openEdit(row)">编辑</el-button>
          <el-button v-if="!row.is_default" size="small" type="primary" plain @click="makeDefault(row)">设为默认</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" :title="editing ? `编辑 ${editing.name}` : '新增供应商'" width="560px">
      <el-form label-width="110px">
        <el-form-item label="名称（唯一）" required>
          <el-input v-model="form.name" placeholder="如 siliconflow / qwen / deepseek" :disabled="!!editing" />
        </el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.provider_type" style="width: 100%">
            <el-option v-for="t in TYPES" :key="t.value" :value="t.value" :label="t.label" />
          </el-select>
        </el-form-item>
        <el-form-item label="Base URL" required>
          <el-input v-model="form.base_url" placeholder="OpenAI 兼容地址，如 https://api.siliconflow.cn/v1" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.api_key" type="password" show-password :placeholder="apiKeyPlaceholder" />
          <span class="key-state" :class="form.api_key_set ? 'set' : 'unset'">
            {{ form.api_key_set ? '已配置' : '未配置' }}
          </span>
        </el-form-item>
        <el-form-item label="对话模型" required>
          <el-select v-model="form.model" filterable allow-create default-first-option placeholder="如 Qwen/Qwen2.5-7B-Instruct" style="width: 100%">
            <el-option v-for="m in chatModels" :key="m" :value="m" :label="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="嵌入模型">
          <el-select v-model="form.embedding_model" filterable allow-create default-first-option clearable placeholder="如 BAAI/bge-m3（对话需向量检索时必填）" style="width: 100%">
            <el-option v-for="m in embeddingModels" :key="m" :value="m" :label="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="重排模型">
          <el-select v-model="form.rerank_model" filterable allow-create default-first-option clearable placeholder="如 BAAI/bge-reranker-v2-m3（调 /rerank 端点）" style="width: 100%">
            <el-option v-for="m in rerankModels" :key="m" :value="m" :label="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="测试模型">
          <el-select v-model="testModel" filterable allow-create default-first-option clearable placeholder="留空则仅测 /models 连通" style="width: 100%">
            <el-option-group v-for="g in modelGroups" :key="g.label" :label="g.label">
              <el-option v-for="m in g.models" :key="m" :value="m" :label="m" />
            </el-option-group>
          </el-select>
          <span class="test-hint">先在列表点「测试」或在弹窗内试跑，探测到的模型按 对话/嵌入/重排 分类，上方三个模型下拉框只显示对应类型；也可手动输入任意模型名</span>
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="form.is_default" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button :loading="testing" @click="dialogTest">测试连通</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listProviders, createProvider, updateProvider, deleteProvider, setDefaultProvider, testProvider } from '../api/provider'
import { useProviderStore } from '../stores/provider'

const store = useProviderStore()
const list = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const testing = ref(false)
const testModel = ref('')        // 编辑框内试跑的模型（可搜索/输入）
const testModels = ref([])       // 当前供应商探测到的可用模型（对话/嵌入/重排下拉框共用）
const modelsCache = reactive({}) // 按供应商名缓存探测结果：测试过再打开编辑，三个模型下拉框直接可选中

// ---- 模型分类：按名称启发式识别 嵌入/重排，其余归为对话 ----
const MODEL_TYPE = { chat: '对话', embedding: '嵌入', rerank: '重排' }
function classifyModel(id) {
  const name = String(id || '').toLowerCase()
  if (/(rerank|cross-encoder)/.test(name)) return 'rerank'
  if (/(text-embedding|embed|bge|e5|gte|m3e|mxbai|jina|nomic|minilm)/.test(name)) return 'embedding'
  return 'chat'
}
const chatModels = computed(() => testModels.value.filter((m) => classifyModel(m) === 'chat'))
const embeddingModels = computed(() => testModels.value.filter((m) => classifyModel(m) === 'embedding'))
const rerankModels = computed(() => testModels.value.filter((m) => classifyModel(m) === 'rerank'))
const modelGroups = computed(() => [
  { label: `对话模型（${chatModels.value.length}）`, models: chatModels.value },
  { label: `嵌入模型（${embeddingModels.value.length}）`, models: embeddingModels.value },
  { label: `重排模型（${rerankModels.value.length}）`, models: rerankModels.value },
])
const form = reactive({ name: '', provider_type: 'siliconflow', base_url: '', api_key: '', model: '', embedding_model: '', rerank_model: '', is_default: false, api_key_set: false })

// Key 已保存时不回显，placeholder 提示已配置；未配置则提示需填写
const apiKeyPlaceholder = computed(() =>
  form.api_key_set
    ? `已保存 Key（${editing.value?.api_key || 'sk-****'}），留空不修改`
    : '未配置 Key，连通测试需要填写',
)

const TYPES = [
  { value: 'siliconflow', label: '硅基流动' },
  { value: 'qwen', label: '通义千问 DashScope' },
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'vllm', label: 'vLLM（自部署）' },
  { value: 'ollama', label: 'Ollama（本地）' },
  { value: 'custom', label: '自定义 OpenAI 兼容' },
]

onMounted(fetchList)

async function fetchList() {
  loading.value = true
  try {
    list.value = await listProviders()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { name: '', provider_type: 'siliconflow', base_url: '', api_key: '', model: '', embedding_model: '', rerank_model: '', is_default: false, api_key_set: false })
  testModel.value = ''
  testModels.value = []
  dialogVisible.value = true
}

function openEdit(row) {
  editing.value = row
  Object.assign(form, {
    name: row.name,
    provider_type: row.provider_type,
    base_url: row.base_url,
    api_key: '', // 不回显 Key，仅用 api_key_set 标记状态
    model: row.model,
    embedding_model: row.embedding_model || '',
    rerank_model: row.rerank_model || '',
    is_default: row.is_default,
    api_key_set: !!row.api_key_set,
  })
  testModel.value = ''
  testModels.value = modelsCache[row.name] || [] // 打开编辑即回填该供应商已探测到的模型
  dialogVisible.value = true
}

// 编辑框内测试连通：可选指定模型做真实对话试跑
async function dialogTest() {
  if (!editing.value) return ElMessage.warning('新增供应商需先保存，保存后再测试连通')
  testing.value = true
  try {
    const res = await testProvider(form.name, { model: testModel.value || undefined })
    if (res.models?.length) {
      modelsCache[form.name] = res.models
      testModels.value = res.models
    }
    ElMessage.success(res.message || '连通正常')
  } catch (e) {
    ElMessage.error(`连通失败：${e.message}`)
  } finally {
    testing.value = false
  }
}

async function submit() {
  if (!form.name.trim() || !form.base_url.trim() || !form.model.trim()) {
    return ElMessage.warning('名称 / Base URL / 对话模型 为必填')
  }
  const payload = { ...form }
  delete payload.api_key_set // 响应字段，不随请求提交
  if (editing.value && !payload.api_key) delete payload.api_key
  try {
    if (editing.value) await updateProvider(editing.value.name, payload)
    else await createProvider(payload)
    ElMessage.success('保存成功')
    dialogVisible.value = false
    await fetchList()
    await store.fetch()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function makeDefault(row) {
  try {
    await setDefaultProvider(row.name)
    ElMessage.success('已设为默认')
    await fetchList()
    await store.fetch()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function test(row) {
  const loading = ElMessage({ type: 'info', message: `正在测试 ${row.name} ...`, duration: 0 })
  try {
    const res = await testProvider(row.name)
    loading.close()
    if (res.models?.length) modelsCache[row.name] = res.models // 缓存，编辑时可直接下拉选择
    const byType = (t) => (res.models || []).filter((m) => classifyModel(m) === t).length
    ElMessage.success(`连通成功：共 ${res.models?.length || 0} 个模型（对话 ${byType('chat')} / 嵌入 ${byType('embedding')} / 重排 ${byType('rerank')}），编辑时可下拉选择`)
  } catch (e) {
    loading.close()
    ElMessage.error(`连通失败：${e.message}`)
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`删除供应商「${row.name}」？`, '提示', { type: 'warning' })
    await deleteProvider(row.name)
    ElMessage.success('已删除')
    await fetchList()
    await store.fetch()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.providers-page {
  padding: 20px;
  height: 100%;
  overflow-y: auto;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.head h3 {
  margin: 0;
}
.key-state {
  margin-left: 8px;
  font-size: 12px;
  line-height: 32px;
}
.key-state.set {
  color: #67c23a;
}
.key-state.unset {
  color: #e6a23c;
}
.test-hint {
  color: #909399;
  font-size: 12px;
  line-height: 1.5;
  margin-top: 4px;
  width: 100%;
}
</style>
