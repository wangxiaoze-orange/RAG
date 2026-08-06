<template>
  <div class="source-panel">
    <div v-for="(s, i) in sources" :key="i" class="source-item">
      <div class="head">
        <span class="idx">[{{ i + 1 }}]</span>
        <span class="doc">{{ s.doc_name }}</span>
        <el-tag size="small" class="route" v-if="s.source_type === 'web'">网页</el-tag>
        <el-tag size="small" class="route" v-else-if="s.source_type === 'memory'">记忆</el-tag>
        <el-tag size="small" class="route" v-else-if="s.hit_routes">{{ s.hit_routes.join('/') }}</el-tag>
      </div>
      <div class="meta" v-if="s.section_title || s.page_number">
        {{ [s.section_title && `第${s.section_title}节`, s.page_number && `第${s.page_number}页`].filter(Boolean).join(' · ') }}
      </div>
      <div class="preview" v-if="s.preview">{{ s.preview }}</div>
      <a v-if="s.web_url" :href="s.web_url" target="_blank" class="link">{{ s.web_url }}</a>
      <div class="score" v-if="typeof s.score === 'number'">相关度 {{ s.score.toFixed(3) }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  sources: { type: Array, default: () => [] },
})
</script>

<style scoped>
.source-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
.source-item {
  background: #f7f9fc;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 8px 12px;
  font-size: 12px;
}
.head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.idx {
  color: #409eff;
  font-weight: 600;
}
.doc {
  font-weight: 600;
  flex: 1;
}
.meta {
  color: #909399;
  margin-top: 2px;
}
.preview {
  color: #606266;
  margin-top: 4px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.link {
  color: #409eff;
  word-break: break-all;
}
.score {
  color: #909399;
  margin-top: 2px;
}
</style>
