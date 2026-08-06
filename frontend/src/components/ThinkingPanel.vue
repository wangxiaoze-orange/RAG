<template>
  <div class="thinking">
    <el-collapse v-model="open">
      <el-collapse-item name="stages">
        <template #title>
          <span class="ttl">推理过程</span>
          <el-tag v-if="thinking.pathType" size="small" class="tag">{{ PATH_NAMES[thinking.pathType] || thinking.pathType }}</el-tag>
          <el-tag v-if="typeof thinking.confidence === 'number'" size="small" type="info" class="tag">
            置信度 {{ thinking.confidence.toFixed(3) }}
          </el-tag>
        </template>

        <!-- 阶段时间线 -->
        <div class="stages" v-if="thinking.stages.length">
          <div v-for="(s, i) in thinking.stages" :key="i" class="stage-row">
            <el-icon class="dot"><Finished /></el-icon>
            <span class="stage-name">{{ s.name }}</span>
            <span class="stage-detail">{{ s.detail }}</span>
            <span class="stage-time">{{ s.ts }}</span>
          </div>
        </div>

        <!-- 意图 -->
        <div v-if="thinking.intent" class="block">
          <div class="block-title">意图识别</div>
          <div class="tags">
            <el-tag size="small" type="warning">{{ SCOPE_NAMES[thinking.intent.scope] || thinking.intent.scope }}</el-tag>
            <el-tag v-for="l in thinking.intent.labels" :key="l" size="small">{{ l }}</el-tag>
            <el-tag v-if="thinking.intent.needs_decomposition" size="small" type="danger">问题拆解</el-tag>
          </div>
          <div v-if="thinking.intent.sub_questions?.length" class="sub-questions">
            <div v-for="(q, i) in thinking.intent.sub_questions" :key="i">• {{ q }}</div>
          </div>
        </div>

        <!-- 工具调用 -->
        <div v-if="thinking.toolCalls.length" class="block">
          <div class="block-title">工具调用（{{ thinking.toolCalls.length }} 次）</div>
          <div v-for="(t, i) in thinking.toolCalls" :key="i" class="tool-row">
            <el-tag size="small" type="success">{{ t.name }}</el-tag>
            <span class="tool-args">{{ JSON.stringify(t.args) }}</span>
            <span class="tool-summary">{{ t.summary }}</span>
          </div>
        </div>

        <!-- 记忆 / 缓存 -->
        <div v-if="thinking.cacheHit" class="block info">⚡ 高频问题缓存命中，直接回放缓存答案</div>
        <div v-if="thinking.memories.length" class="block info">
          记忆抽取：{{ thinking.memories.map((m) => `${m.content}（${m.type}）`).join('、') }}
        </div>

        <!-- 审查 -->
        <div v-if="thinking.review" class="block">
          <div class="block-title">自纠错审查</div>
          <el-tag size="small" :type="thinking.review.conclusion === 'pass' ? 'success' : 'danger'">
            {{ thinking.review.conclusion === 'pass' ? '通过' : '未通过' }} · {{ thinking.review.score }}
          </el-tag>
          <div v-if="thinking.review.issues?.length" class="issues">
            <div v-for="(issue, i) in thinking.review.issues" :key="i">• {{ issue }}</div>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  thinking: { type: Object, required: true },
})
const open = ref(props.thinking?.stages?.length ? ['stages'] : [])

const PATH_NAMES = {
  standard: '标准检索',
  overview: '知识库概览',
  document_scope: '文档直读',
  cache_replay: '缓存回放',
  fallback: '常识兜底',
}
const SCOPE_NAMES = {
  kb: '知识库问答',
  web: '实时网页',
  mixed: '混合检索',
  memory: '个性化记忆',
  chat: '闲聊',
  direct: '文档直读',
}
</script>

<style scoped>
.thinking {
  margin-top: 6px;
  border: 1px dashed #dcdfe6;
  border-radius: 8px;
  padding: 0 8px;
  background: #fafbfd;
}
.ttl {
  font-size: 13px;
  font-weight: 600;
  margin-right: 8px;
}
.tag {
  margin-left: 6px;
}
.stages {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 0;
}
.stage-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.dot {
  color: #67c23a;
}
.stage-name {
  font-weight: 600;
}
.stage-detail {
  color: #606266;
}
.stage-time {
  color: #c0c4cc;
  font-size: 11px;
}
.block {
  padding: 8px 0;
  border-top: 1px solid #f0f2f5;
}
.block-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 6px;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.sub-questions,
.issues {
  font-size: 12px;
  color: #606266;
  margin-top: 6px;
}
.tool-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  padding: 3px 0;
}
.tool-args {
  color: #606266;
  font-family: monospace;
}
.tool-summary {
  color: #909399;
}
.info {
  font-size: 12px;
  color: #67c23a;
}
</style>
