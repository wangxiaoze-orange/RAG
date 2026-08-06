<template>
  <div class="chat-page">
    <!-- 左侧：会话列表 -->
    <aside class="sidebar">
      <el-button type="primary" class="new-btn" @click="newConversation">
        <el-icon><Plus /></el-icon>&nbsp;新对话
      </el-button>
      <div class="conv-list">
        <div
          v-for="c in conversations"
          :key="c.id"
          class="conv-item"
          :class="{ active: c.id === currentConvId }"
          @click="loadConversation(c.id)"
        >
          <span class="conv-title">{{ c.title }}</span>
          <el-icon class="del" @click.stop="removeConversation(c.id)"><Delete /></el-icon>
        </div>
        <el-empty v-if="!conversations.length" description="暂无会话" :image-size="60" />
      </div>
    </aside>

    <!-- 右侧：聊天区 -->
    <section class="chat-main">
      <div class="toolbar">
        <el-select
          v-model="providerName"
          placeholder="对话模型"
          size="small"
          style="width: 180px"
          :disabled="!providerStore.list.length"
        >
          <el-option
            v-for="p in providerStore.list"
            :key="p.name"
            :value="p.name"
            :label="`${p.name}${p.is_default ? '（默认）' : ''}`"
          />
        </el-select>
        <el-select
          v-model="selectedKbIds"
          multiple
          collapse-tags
          placeholder="不选则纯对话（不检索知识库）"
          size="small"
          style="width: 320px"
        >
          <el-option v-if="kbs.length" :value="ALL_KBS" label="全部知识库" />
          <el-option v-for="kb in kbs" :key="kb.id" :value="kb.id" :label="`${kb.name}（${kb.doc_count} 文档）`" />
        </el-select>
      </div>

      <div ref="msgBox" class="messages">
        <template v-if="messages.length">
          <ChatMessage v-for="m in messages" :key="m.id" :msg="m" />
        </template>
        <el-empty v-else description="开始提问吧，例如「我的知识库里都有什么？」" />
      </div>

      <div class="input-area">
        <el-input
          v-model="question"
          type="textarea"
          :rows="3"
          resize="none"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行"
          @keydown.enter.exact.prevent="send"
        />
        <div class="input-bar">
          <span class="hint">问题会经过 16 步流水线：缓存检查 → 意图识别 → 多路检索 → RRF 融合 → 重排 → 生成</span>
          <el-button v-if="!sending" type="primary" :disabled="!question.trim()" @click="send">发送</el-button>
          <el-button v-else type="danger" @click="stop">停止</el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import ChatMessage from '../components/ChatMessage.vue'
import { chatStream } from '../utils/sse'
import { listConversations, listMessages, deleteConversation } from '../api/conversation'
import { listKbs } from '../api/kb'
import { useProviderStore } from '../stores/provider'

const providerStore = useProviderStore()
const conversations = ref([])
const currentConvId = ref(null)
const kbs = ref([])
const selectedKbIds = ref([])
const ALL_KBS = '__all__' // 「全部知识库」哨兵值：选中 → 发送全部知识库 id；一个不选 → 纯对话模式
const providerName = ref('')
const messages = ref([])
const question = ref('')
const sending = ref(false)
const msgBox = ref()
let ctrl = null

onMounted(async () => {
  await Promise.all([refreshConversations(), refreshKbs(), providerStore.fetch()])
  if (providerStore.list.length) providerName.value = providerStore.defaultProvider?.name || providerStore.list[0].name
  if (conversations.value.length) loadConversation(conversations.value[0].id)
})

onBeforeUnmount(() => stop())

function scrollBottom() {
  nextTick(() => {
    if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight
  })
}

async function refreshConversations() {
  conversations.value = await listConversations()
}

async function refreshKbs() {
  kbs.value = await listKbs()
}

function newConversation() {
  currentConvId.value = null
  messages.value = []
  question.value = ''
}

async function loadConversation(id) {
  if (sending.value) stop()
  currentConvId.value = id
  const rows = await listMessages(id)
  messages.value = rows.map((m) => ({
    id: m.id,
    role: m.role,
    content: m.content || '',
    streaming: false,
    error: '',
    sources: m.sources || [],
    thinking: m.reflection
      ? {
          stages: [],
          toolCalls: [],
          intent: null,
          review: m.reflection,
          cacheHit: m.cache_hit,
          memories: [],
          pathType: m.path_type,
          confidence: m.confidence,
        }
      : null,
  }))
  scrollBottom()
}

async function removeConversation(id) {
  await ElMessageBox.confirm('删除该会话及全部消息？', '提示', { type: 'warning' })
  await deleteConversation(id)
  if (currentConvId.value === id) newConversation()
  refreshConversations()
}

function resolveKbIds() {
  if (selectedKbIds.value.includes(ALL_KBS)) return kbs.value.map((k) => k.id)
  return selectedKbIds.value // 空数组 → 后端走纯对话（闲聊）模式
}

async function send() {
  const q = question.value.trim()
  if (!q || sending.value) return
  if (!providerStore.list.length) {
    ElMessage.warning('请先在「模型供应商」页配置并启用一个供应商')
    return
  }
  // 必须用 reactive 创建：事件回调里 ai.content += 需要触发界面刷新。
  // 用普通对象的话，改的是原始对象，不触发渲染 → 回复永远不显示（只看到「加载中」）
  const ai = reactive({
    id: `a-${Date.now()}`,
    role: 'assistant',
    content: '',
    streaming: true,
    error: '',
    sources: [],
    thinking: { stages: [], toolCalls: [], intent: null, review: null, cacheHit: false, memories: [], pathType: null, confidence: null },
  })
  messages.value.push({ id: `u-${Date.now()}`, role: 'user', content: q, streaming: false, error: '' })
  messages.value.push(ai)
  question.value = ''
  sending.value = true
  ctrl = new AbortController()
  scrollBottom()

  const onEvent = (evt, data) => {
    switch (evt) {
      case 'session':
        currentConvId.value = data.conversation_id
        break
      case 'stage':
        ai.thinking.stages.push({ name: data.name, detail: data.detail || '', ts: new Date().toLocaleTimeString() })
        break
      case 'tool_call':
        ai.thinking.toolCalls.push({ name: data.name, args: data.args || {}, summary: data.summary || '' })
        break
      case 'token':
        ai.content += data.delta || data.content || ''
        break
      case 'cache_hit':
        ai.thinking.cacheHit = true
        break
      case 'memory':
        ai.thinking.memories.push(...(data.saved || []))
        break
      case 'intent':
        ai.thinking.intent = data
        break
      case 'review':
        ai.thinking.review = data
        break
      case 'error':
        ai.error = data.message || '未知错误'
        break
      case 'done':
        ai.thinking.pathType = data.path_type
        ai.thinking.confidence = data.confidence
        ai.sources = data.sources || []
        // 兜底：token 流事件若丢失/被缓冲，用 done 携带的完整答案整段渲染
        if (data.answer && !ai.content) ai.content = data.answer
        if (data.use_fallback) ai.error = resolveKbIds().length ? '未检索到知识库相关内容，以下为基于通用知识的回答' : '未选择知识库，以下为模型直接回答'
        break
    }
    scrollBottom()
  }

  try {
    await chatStream(
      {
        question: q,
        conversation_id: currentConvId.value || undefined,
        kb_ids: resolveKbIds(),
        provider_name: providerName.value || undefined,
      },
      { onEvent },
      { signal: ctrl.signal },
    )
  } catch (e) {
    if (e.name !== 'AbortError') ai.error = e.message
  } finally {
    ai.streaming = false
    sending.value = false
    scrollBottom()
    refreshConversations().catch(() => {})
  }
}

function stop() {
  ctrl?.abort()
}
</script>

<style scoped>
.chat-page {
  height: 100%;
  display: flex;
}
.sidebar {
  width: 240px;
  background: #fff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  padding: 12px;
  gap: 10px;
}
.new-btn {
  width: 100%;
}
.conv-list {
  flex: 1;
  overflow-y: auto;
}
.conv-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.conv-item:hover {
  background: #f5f7fa;
}
.conv-item.active {
  background: #ecf5ff;
  color: #409eff;
}
.conv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.del {
  color: #c0c4cc;
  visibility: hidden;
}
.conv-item:hover .del {
  visibility: visible;
}
.del:hover {
  color: #f56c6c;
}
.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.toolbar {
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  gap: 12px;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 18px 24px;
}
.input-area {
  background: #fff;
  border-top: 1px solid #e4e7ed;
  padding: 10px 16px;
}
.input-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
}
.hint {
  color: #c0c4cc;
  font-size: 12px;
}
</style>
