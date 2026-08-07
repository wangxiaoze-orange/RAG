<template>
  <div class="faq-page">
    <!-- ============ 普通用户：搜索经验库 ============ -->
    <div v-if="!userStore.isAdmin" class="search-zone">
      <h3>经验库搜索</h3>
      <p class="sub">搜索已发布的高频问题经验，命中后直接展示答案（不走检索流水线）</p>
      <div class="search-bar">
        <el-input v-model="searchQ" placeholder="输入问题关键词" clearable @keyup.enter="doSearch" />
        <el-button type="primary" :loading="searching" @click="doSearch">搜索</el-button>
      </div>
      <div v-loading="searching" class="result-list">
        <el-card v-for="f in searchResults" :key="f.id" class="faq-card" shadow="hover">
          <div class="faq-q">{{ f.question }}</div>
          <div v-if="f.rewritten_question && f.rewritten_question !== f.question" class="faq-rq">
            改写问题：{{ f.rewritten_question }}
          </div>
          <el-divider style="margin: 10px 0" />
          <div class="faq-a">{{ f.answer }}</div>
          <div class="faq-meta">
            <el-tag size="small" type="info">命中 {{ f.hit_count }} 次</el-tag>
            <span v-if="f.expire_at" class="expire">有效期至 {{ fmtTime(f.expire_at) }}</span>
          </div>
        </el-card>
        <el-empty v-if="searched && !searchResults.length && !searching" description="未找到相关经验" />
      </div>
    </div>

    <!-- ============ 管理员：审核 + 管理 ============ -->
    <template v-else>
      <el-tabs v-model="tab" @tab-change="loadList">
        <el-tab-pane label="待审核" name="pending" />
        <el-tab-pane label="已发布" name="published" />
        <el-tab-pane label="已停用" name="disabled" />
      </el-tabs>
      <div class="toolbar">
        <el-input v-model="kw" placeholder="搜索问题/答案" clearable style="width: 260px" @keyup.enter="loadList" @clear="loadList" />
        <el-button type="primary" @click="loadList">搜索</el-button>
      </div>
      <el-table :data="faqs" v-loading="loading" stripe>
        <el-table-column label="原始问题" min-width="200">
          <template #default="{ row }">
            <div class="cell-q">{{ row.question }}</div>
            <div v-if="row.rewritten_question" class="cell-rq">改写：{{ row.rewritten_question }}</div>
          </template>
        </el-table-column>
        <el-table-column label="答案" min-width="240">
          <template #default="{ row }">
            <div class="cell-a">{{ row.answer }}</div>
          </template>
        </el-table-column>
        <el-table-column label="频次/命中" width="100">
          <template #default="{ row }">{{ row.freq }} / {{ row.hit_count }}</template>
        </el-table-column>
        <el-table-column label="有效期" width="180">
          <template #default="{ row }">
            <span v-if="row.expire_at">{{ fmtTime(row.expire_at) }}</span>
            <span v-else class="muted">永久</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220">
          <template #default="{ row }">
            <el-button v-if="row.status === 'pending'" size="small" type="success" @click="doPublish(row)">发布</el-button>
            <el-button v-if="row.status === 'published'" size="small" type="warning" plain @click="doDisable(row)">停用</el-button>
            <el-button v-if="row.status === 'disabled'" size="small" type="success" plain @click="doPublish(row)">重新发布</el-button>
            <el-button size="small" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" plain @click="doDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 编辑：答案 + 有效期 -->
      <el-dialog v-model="editVisible" title="编辑经验条目" width="560px">
        <el-form label-width="80px">
          <el-form-item label="原始问题">
            <el-input v-model="editForm.question" />
          </el-form-item>
          <el-form-item label="改写问题">
            <el-input v-model="editForm.rewritten_question" placeholder="（可选）" />
          </el-form-item>
          <el-form-item label="答案">
            <el-input v-model="editForm.answer" type="textarea" :rows="6" />
          </el-form-item>
          <el-form-item label="有效期">
            <el-date-picker
              v-model="editForm.expire_at"
              type="datetime"
              placeholder="留空为永久有效"
              clearable
              style="width: 100%"
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editVisible = false">取消</el-button>
          <el-button type="primary" @click="submitEdit">保存</el-button>
        </template>
      </el-dialog>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '../stores/user'
import { listFaqs, updateFaq, publishFaq, disableFaq, deleteFaq, searchFaqs } from '../api/admin'

const userStore = useUserStore()

// 管理员
const tab = ref('pending')
const kw = ref('')
const faqs = ref([])
const loading = ref(false)
const editVisible = ref(false)
const editForm = reactive({ id: null, question: '', rewritten_question: '', answer: '', expire_at: null })

// 普通用户搜索
const searchQ = ref('')
const searchResults = ref([])
const searching = ref(false)
const searched = ref(false)

onMounted(() => {
  if (userStore.isAdmin) loadList()
})

function fmtTime(s) {
  return s ? new Date(s).toLocaleString() : '—'
}

async function loadList() {
  loading.value = true
  try {
    faqs.value = await listFaqs({ status: tab.value, q: kw.value })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function doSearch() {
  searched.value = true
  searching.value = true
  try {
    searchResults.value = await searchFaqs(searchQ.value)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    searching.value = false
  }
}

function openEdit(row) {
  editForm.id = row.id
  editForm.question = row.question
  editForm.rewritten_question = row.rewritten_question || ''
  editForm.answer = row.answer
  editForm.expire_at = row.expire_at ? new Date(row.expire_at) : null
  editVisible.value = true
}

async function submitEdit() {
  if (!editForm.answer.trim()) return ElMessage.warning('答案不能为空')
  try {
    await updateFaq(editForm.id, {
      question: editForm.question,
      rewritten_question: editForm.rewritten_question || null,
      answer: editForm.answer,
      expire_at: editForm.expire_at ? new Date(editForm.expire_at).toISOString() : null,
    })
    ElMessage.success('已保存')
    editVisible.value = false
    loadList()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function doPublish(row) {
  try {
    await publishFaq(row.id)
    ElMessage.success('已发布，流水线将直接读该经验')
    loadList()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function doDisable(row) {
  try {
    await disableFaq(row.id)
    ElMessage.success('已停用')
    loadList()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function doDelete(row) {
  try {
    await ElMessageBox.confirm(`删除经验「${row.question.slice(0, 30)}…」？不可恢复`, '危险操作', { type: 'warning' })
    await deleteFaq(row.id)
    ElMessage.success('已删除')
    loadList()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.faq-page {
  padding: 20px;
  height: 100%;
  overflow-y: auto;
}
.sub {
  color: #909399;
  font-size: 13px;
}
.search-bar {
  display: flex;
  gap: 10px;
  max-width: 520px;
  margin-bottom: 16px;
}
.result-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 860px;
}
.faq-card .faq-q {
  font-weight: 600;
  font-size: 15px;
}
.faq-card .faq-rq {
  color: #409eff;
  font-size: 13px;
  margin-top: 4px;
}
.faq-card .faq-a {
  font-size: 13px;
  color: #606266;
  line-height: 1.7;
  white-space: pre-wrap;
}
.faq-card .faq-meta {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.expire {
  color: #909399;
  font-size: 12px;
}
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.cell-q {
  font-weight: 600;
  font-size: 13px;
}
.cell-rq {
  color: #409eff;
  font-size: 12px;
  margin-top: 2px;
}
.cell-a {
  font-size: 12px;
  color: #606266;
  max-height: 80px;
  overflow: hidden;
  white-space: pre-wrap;
}
.muted {
  color: #909399;
  font-size: 12px;
}
</style>
