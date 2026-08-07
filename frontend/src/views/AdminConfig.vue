<template>
  <div class="config-page">
    <div class="head">
      <div>
        <h3>流水线配置</h3>
        <p class="sub">修改后经配置中心双写（etcd + MySQL），约 10 秒内全量生效。仅管理员可编辑。</p>
      </div>
      <el-button type="primary" :loading="saving" :disabled="!dirtyCount" @click="saveAll">
        保存修改<template v-if="dirtyCount">（{{ dirtyCount }} 项）</template>
      </el-button>
    </div>

    <div v-loading="loading">
      <template v-for="g in GROUPS" :key="g.key">
        <div v-if="itemsByGroup[g.key]?.length" class="group">
          <h4>{{ g.label }}</h4>
          <el-form label-width="0">
            <div v-for="item in itemsByGroup[g.key]" :key="item.key" class="item">
              <div class="item-label">
                <code>{{ item.key }}</code>
                <span class="desc">{{ item.desc }}</span>
                <span v-if="isDirty(item.key)" class="dirty-tag">已修改</span>
              </div>
              <div class="item-input">
                <el-switch v-if="item.type === 'bool'" v-model="values[item.key]" />
                <el-input-number v-else-if="item.type === 'int'" v-model="values[item.key]" :step="1" controls-position="right" style="width: 180px" />
                <el-input-number v-else-if="item.type === 'float'" v-model="values[item.key]" :step="0.05" :precision="4" controls-position="right" style="width: 180px" />
                <el-select v-else-if="item.key === 'rag.chunk_strategy'" v-model="values[item.key]" style="width: 180px">
                  <el-option label="Markdown 结构切分" value="markdown" />
                  <el-option label="固定长度" value="fixed" />
                  <el-option label="语义切分" value="semantic" />
                  <el-option label="父子切片" value="parent_child" />
                </el-select>
                <el-input
                  v-else-if="item.type === 'json'"
                  v-model="jsonText[item.key]"
                  type="textarea"
                  :rows="3"
                  :class="{ 'json-error': jsonError[item.key] }"
                  placeholder='JSON，如 {"need_vector": 1.0, "need_bm25": 1.0}'
                  @input="() => onJsonInput(item.key)"
                />
                <el-input v-else v-model="values[item.key]" style="width: 260px" />
                <el-button text type="primary" class="reset" :disabled="!isDirty(item.key)" @click="resetOne(item)">恢复</el-button>
              </div>
            </div>
          </el-form>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getConfig, setConfig } from '../api/admin'

const GROUPS = [
  { key: 'generate', label: '生成参数（温度 / 召回数 / 压缩预算）' },
  { key: 'cache', label: '缓存与经验库' },
  { key: 'retrieve', label: '检索与置信度（rerank 阈值）' },
  { key: 'intent', label: '意图与召回配额（标签权重）' },
  { key: 'ingestion', label: '入库配置（切片策略 / 解析置信度）' },
  { key: 'other', label: '其他' },
]

const loading = ref(false)
const saving = ref(false)
const items = ref([])
const values = reactive({})     // key → 当前编辑值
const baseline = reactive({})   // key → 服务端值（用于判断脏数据）
const jsonText = reactive({})   // json 类型的文本编辑态
const jsonError = reactive({})

const itemsByGroup = computed(() => {
  const map = {}
  for (const it of items.value) (map[it.group] ||= []).push(it)
  return map
})

const dirtyKeys = computed(() => items.value.filter((it) => isDirty(it.key)).map((it) => it.key))
const dirtyCount = computed(() => dirtyKeys.value.length)

onMounted(load)

async function load() {
  loading.value = true
  try {
    items.value = await getConfig()
    for (const it of items.value) {
      const v = it.value === null || it.value === undefined ? it.default : it.value
      values[it.key] = v
      baseline[it.key] = deepCopy(v)
      if (it.type === 'json') {
        jsonText[it.key] = v == null ? '' : JSON.stringify(v, null, 2)
        jsonError[it.key] = false
      }
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function deepCopy(v) {
  return v == null ? v : JSON.parse(JSON.stringify(v))
}

function isDirty(key) {
  return JSON.stringify(values[key]) !== JSON.stringify(baseline[key])
}

function onJsonInput(key) {
  const text = (jsonText[key] || '').trim()
  if (!text) {
    values[key] = null
    jsonError[key] = false
    return
  }
  try {
    values[key] = JSON.parse(text)
    jsonError[key] = false
  } catch (e) {
    jsonError[key] = true
  }
}

function resetOne(item) {
  values[item.key] = deepCopy(baseline[item.key])
  if (item.type === 'json') {
    jsonText[item.key] = baseline[item.key] == null ? '' : JSON.stringify(baseline[item.key], null, 2)
    jsonError[item.key] = false
  }
}

async function saveAll() {
  for (const key of dirtyKeys.value) {
    if (jsonError[key]) return ElMessage.error(`${key} 不是合法 JSON，请修正后再保存`)
  }
  const payload = {}
  for (const key of dirtyKeys.value) payload[key] = values[key]
  saving.value = true
  try {
    await setConfig(payload)
    ElMessage.success(`已保存 ${dirtyKeys.value.length} 项配置，约 10 秒内生效`)
    await load()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.config-page {
  padding: 20px;
  height: 100%;
  overflow-y: auto;
}
.head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 12px;
}
.head h3 {
  margin: 0 0 4px;
}
.sub {
  color: #909399;
  font-size: 13px;
  margin: 0;
}
.group {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 16px;
}
.group h4 {
  margin: 0 0 12px;
  font-size: 15px;
}
.item {
  padding: 10px 0;
  border-bottom: 1px dashed #ebeef5;
}
.item:last-child {
  border-bottom: none;
}
.item-label {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  flex-wrap: wrap;
}
.item-label code {
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
.desc {
  color: #606266;
  font-size: 13px;
}
.dirty-tag {
  color: #e6a23c;
  font-size: 12px;
}
.item-input {
  display: flex;
  align-items: center;
  gap: 8px;
}
.reset {
  margin-left: 8px;
}
.json-error :deep(.el-textarea__inner) {
  border-color: #f56c6c;
}
</style>
