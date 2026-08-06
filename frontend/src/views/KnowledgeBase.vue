<template>
  <div class="kb-page">
    <div class="head">
      <h3>知识库</h3>
      <el-button type="primary" @click="openCreate">
        <el-icon><Plus /></el-icon>&nbsp;新建知识库
      </el-button>
    </div>

    <el-row :gutter="16">
      <el-col v-for="kb in kbs" :key="kb.id" :span="8">
        <el-card class="kb-card" shadow="hover">
          <div class="kb-head">
            <span class="kb-name">{{ kb.name }}</span>
            <el-dropdown @command="(cmd) => onKbCommand(cmd, kb)">
              <el-button text><el-icon><MoreFilled /></el-icon></el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="upload">上传文档</el-dropdown-item>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <p class="kb-desc">{{ kb.description || '暂无描述' }}</p>
          <div class="kb-meta">
            <el-tag size="small">{{ kb.doc_count }} 文档</el-tag>
            <el-tag size="small" type="info">{{ kb.chunk_count }} 切片</el-tag>
          </div>
          <el-divider style="margin: 10px 0" />
          <div class="docs" v-loading="docsLoading[kb.id]">
            <div v-for="d in docsByKb[kb.id] || []" :key="d.id" class="doc-row">
              <el-icon class="doc-icon"><Document /></el-icon>
              <span class="doc-name" :title="d.filename" @click="previewChunks(kb, d)">{{ d.filename }}</span>
              <el-tooltip v-if="d.status === 'failed'" :content="d.error_msg || '解析失败，点击重试'">
                <el-tag size="small" type="danger">{{ STATUS_TEXT[d.status] || d.status }}</el-tag>
              </el-tooltip>
              <el-tag v-else size="small" :type="STATUS_TAG[d.status] || 'info'">{{ STATUS_TEXT[d.status] || d.status }}</el-tag>
              <el-icon class="doc-del" title="删除文档" @click="removeDoc(d)"><Delete /></el-icon>
              <el-icon v-if="d.status === 'failed'" class="doc-retry" title="重试" @click="retryDoc(d)"><Refresh /></el-icon>
            </div>
            <el-empty v-if="!docsByKb[kb.id]?.length" description="暂无文档" :image-size="50" />
            <!-- 上传拖拽区 -->
            <el-upload
              class="uploader"
              drag
              :show-file-list="false"
              :http-request="(opt) => doUpload(kb, opt)"
              :disabled="uploading[kb.id]"
            >
              <div v-if="uploading[kb.id]" class="upload-progress">
                <el-progress :percentage="uploadProgress[kb.id] || 0" :stroke-width="8" style="width: 100%" />
                <span class="upload-note">上传中…（解析入库由后台任务执行）</span>
              </div>
              <div v-else class="upload-hint">
                <el-icon><UploadFilled /></el-icon>
                <span>拖拽或点击上传 PDF / Word / Markdown / TXT</span>
              </div>
            </el-upload>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 新建/重命名 -->
    <el-dialog v-model="createVisible" :title="editing ? '重命名知识库' : '新建知识库'" width="420px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="form.name" maxlength="128" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" maxlength="512" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="submitKb">保存</el-button>
      </template>
    </el-dialog>

    <!-- 切片预览 -->
    <el-dialog v-model="chunksVisible" :title="`切片预览 — ${previewDoc?.filename || ''}`" width="720px">
      <div v-loading="chunksLoading" class="chunk-list">
        <div v-for="c in chunks" :key="c.id" class="chunk-item">
          <div class="chunk-meta">
            <el-tag size="small">#{{ c.chunk_index + 1 }}</el-tag>
            <span v-if="c.section_title" class="chunk-sec">{{ c.section_title }}</span>
            <span v-if="c.page_number" class="chunk-page">第{{ c.page_number }}页</span>
          </div>
          <p class="chunk-content">{{ c.content }}</p>
        </div>
        <el-empty v-if="!chunks.length && !chunksLoading" description="暂无切片" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listKbs, createKb, updateKb, deleteKb, listDocuments, uploadDocument, deleteDocument, retryDocument, listChunks } from '../api/kb'

const kbs = ref([])
const docsByKb = reactive({})
const docsLoading = reactive({})
const uploading = reactive({})
const uploadProgress = reactive({})
const createVisible = ref(false)
const editing = ref(null)
const form = reactive({ name: '', description: '' })
const chunksVisible = ref(false)
const chunks = ref([])
const chunksLoading = ref(false)
const previewDoc = ref(null)

const STATUS_TEXT = {
  uploaded: '待解析',
  parsing: '解析中',
  cleaning: '清洗中',
  chunking: '分块中',
  embedding: '嵌入中',
  ready: '就绪',
  failed: '失败',
}
const STATUS_TAG = {
  ready: 'success',
  failed: 'danger',
  parsing: 'warning',
  cleaning: 'warning',
  chunking: 'warning',
  embedding: 'warning',
}

onMounted(refresh)

async function refresh() {
  kbs.value = await listKbs()
  kbs.value.forEach((kb) => {
    docsByKb[kb.id] = docsByKb[kb.id] || []
    loadDocs(kb.id)
  })
}

async function loadDocs(kbId) {
  docsLoading[kbId] = true
  try {
    docsByKb[kbId] = await listDocuments(kbId)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    docsLoading[kbId] = false
  }
}

function openCreate() {
  editing.value = null
  form.name = ''
  form.description = ''
  createVisible.value = true
}

async function submitKb() {
  if (!form.name.trim()) return ElMessage.warning('请输入名称')
  try {
    if (editing.value) await updateKb(editing.value.id, { name: form.name, description: form.description })
    else await createKb({ name: form.name, description: form.description })
    ElMessage.success('保存成功')
    createVisible.value = false
    refresh()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function onKbCommand(cmd, kb) {
  if (cmd === 'rename') {
    editing.value = kb
    form.name = kb.name
    form.description = kb.description || ''
    createVisible.value = true
  } else if (cmd === 'delete') {
    try {
      await ElMessageBox.confirm(`删除知识库「${kb.name}」及其全部文档/切片？此操作不可恢复`, '危险操作', { type: 'warning' })
      await deleteKb(kb.id)
      ElMessage.success('已删除')
      refresh()
    } catch (e) {
      if (e !== 'cancel') ElMessage.error(e.message)
    }
  }
}

async function doUpload(kb, opt) {
  uploading[kb.id] = true
  uploadProgress[kb.id] = 0
  try {
    await uploadDocument(kb.id, opt.file, (evt) => {
      if (evt.total) uploadProgress[kb.id] = Math.round((evt.loaded / evt.total) * 100)
    })
    ElMessage.success('上传成功，已投递后台解析')
    loadDocs(kb.id)
    refresh()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    uploading[kb.id] = false
  }
}

async function removeDoc(doc) {
  try {
    await ElMessageBox.confirm(`删除文档「${doc.filename}」及全部切片？`, '提示', { type: 'warning' })
    await deleteDocument(doc.id)
    loadDocs(doc.kb_id)
    refresh()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.message)
  }
}

async function retryDoc(doc) {
  try {
    await retryDocument(doc.id)
    ElMessage.success('已重新投递解析')
    loadDocs(doc.kb_id)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function previewChunks(kb, doc) {
  previewDoc.value = doc
  chunksVisible.value = true
  chunksLoading.value = true
  try {
    chunks.value = await listChunks(kb.id, { doc_id: doc.id })
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    chunksLoading.value = false
  }
}
</script>

<style scoped>
.kb-page {
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
.kb-card {
  margin-bottom: 16px;
}
.kb-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.kb-name {
  font-size: 16px;
  font-weight: 600;
}
.kb-desc {
  color: #909399;
  font-size: 13px;
  margin: 6px 0;
  min-height: 18px;
}
.docs {
  max-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.doc-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  padding: 3px 0;
}
.doc-icon {
  color: #909399;
}
.doc-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  color: #303133;
}
.doc-name:hover {
  color: #409eff;
}
.doc-del,
.doc-retry {
  color: #c0c4cc;
  cursor: pointer;
}
.doc-del:hover {
  color: #f56c6c;
}
.doc-retry:hover {
  color: #e6a23c;
}
.uploader {
  margin-top: 8px;
}
.upload-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  color: #909399;
  font-size: 12px;
  padding: 6px 0;
}
.upload-progress {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 16px 12px;
}
.upload-note {
  color: #909399;
  font-size: 12px;
}
.chunk-list {
  max-height: 480px;
  overflow-y: auto;
}
.chunk-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 8px;
}
.chunk-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 4px;
}
.chunk-sec {
  font-size: 12px;
  color: #409eff;
}
.chunk-page {
  font-size: 12px;
  color: #909399;
}
.chunk-content {
  margin: 0;
  font-size: 13px;
  color: #606266;
  line-height: 1.6;
  max-height: 90px;
  overflow: hidden;
}
</style>
