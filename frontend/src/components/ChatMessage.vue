<template>
  <div class="msg" :class="msg.role">
    <div class="avatar">{{ msg.role === 'user' ? '我' : 'R' }}</div>
    <div class="body">
      <div class="bubble" v-if="msg.role === 'user'">{{ msg.content }}</div>
      <div class="bubble md" v-else>
        <!-- eslint-disable-next-line vue/no-v-html -->
        <div v-html="rendered" />
        <span v-if="msg.streaming" class="cursor">▍</span>
      </div>

      <div v-if="msg.error" class="error">{{ msg.error }}</div>

      <!-- 助手消息：推理过程 + 来源 -->
      <template v-if="msg.role === 'assistant' && msg.thinking">
        <ThinkingPanel v-if="msg.thinking.stages.length || msg.thinking.toolCalls.length || msg.thinking.intent || msg.thinking.review" :thinking="msg.thinking" />
        <el-collapse v-if="msg.sources?.length" class="sources">
          <el-collapse-item title="参考来源">
            <SourcePanel :sources="msg.sources" />
          </el-collapse-item>
        </el-collapse>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'
import ThinkingPanel from './ThinkingPanel.vue'
import SourcePanel from './SourcePanel.vue'

const props = defineProps({
  msg: { type: Object, required: true },
})

const md = new MarkdownIt({
  html: false,
  linkify: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang }).value}</code></pre>`
      } catch {
        /* 落到默认转义 */
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(code)}</code></pre>`
  },
})

const rendered = computed(() => md.render(props.msg.content || ''))
</script>

<style scoped>
.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
}
.msg.user {
  flex-direction: row-reverse;
}
.avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
  color: #fff;
}
.msg.user .avatar {
  background: #409eff;
}
.msg.assistant .avatar {
  background: #67c23a;
}
.body {
  max-width: 78%;
  min-width: 0;
}
.msg.user .body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}
.bubble {
  padding: 10px 14px;
  border-radius: 10px;
  line-height: 1.6;
  font-size: 14px;
  word-break: break-word;
}
.msg.user .bubble {
  background: #409eff;
  color: #fff;
  border-top-right-radius: 2px;
}
.msg.assistant .bubble {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-top-left-radius: 2px;
}
.cursor {
  animation: blink 1s infinite;
}
@keyframes blink {
  50% {
    opacity: 0;
  }
}
.error {
  color: #f56c6c;
  font-size: 13px;
  margin-top: 6px;
}
.sources {
  margin-top: 6px;
}
:deep(.md pre) {
  background: #f6f8fa;
  padding: 10px;
  border-radius: 6px;
  overflow-x: auto;
}
:deep(.md code) {
  font-family: 'JetBrains Mono', Consolas, monospace;
  font-size: 13px;
}
:deep(.md p) {
  margin: 6px 0;
}
</style>
