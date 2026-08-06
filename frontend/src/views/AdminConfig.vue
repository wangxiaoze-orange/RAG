<template>
  <div class="config-page">
    <h3>流水线配置说明</h3>
    <p class="sub">
      以下参数为 16 步聊天流水线的可调项，默认值内置在代码中。正式环境通过 etcd（<code>/config/rag/*</code>）覆盖，
      启动脚本 <code>deploy/etcd/seed-config.sh</code> 负责初始化。修改 etcd 后 10 秒内生效（配置中心 TTL 缓存）。
    </p>
    <el-table :data="ITEMS" stripe>
      <el-table-column prop="key" label="配置键" width="320" />
      <el-table-column prop="default" label="默认值" width="120" />
      <el-table-column prop="desc" label="说明" min-width="360" />
    </el-table>
  </div>
</template>

<script setup>
const ITEMS = [
  { key: 'rag.feature.cache_enabled', default: 'true', desc: '② 缓存检查总开关（灰度开关）' },
  { key: 'rag.cache_freq_threshold', default: '3', desc: '② 防穿透：同一问题被问够 3 次后才读缓存' },
  { key: 'rag.cache_write_min_freq', default: '3', desc: '⑯ 高频问题累计次数达标后写入缓存' },
  { key: 'rag.memory_ttl_days', default: '30', desc: '⑥ 显式记忆过期天数' },
  { key: 'rag.feature.agent_retrieval_enabled', default: 'true', desc: '⑦ ReAct 智能检索开关，关闭后走规则路由' },
  { key: 'rag.feature.web_search_enabled', default: 'true', desc: '⑦ 网页检索开关（DuckDuckGo）' },
  { key: 'rag.document_scope_chunk_budget', default: '18', desc: '⑤ 文档直读切片预算（每文档至少 4 片，均匀抽样）' },
  { key: 'rag.rrf_top_k', default: '15', desc: '⑨ RRF 融合保留 Top N' },
  { key: 'rag.rerank_top_n', default: '6', desc: '⑩ 重排后保留 Top N（硅基流动 bge-reranker-v2-m3）' },
  { key: 'rag.compress_budget_tokens', default: '3000', desc: '⑪ 上下文压缩 token 预算' },
  { key: 'rag.confidence_threshold', default: '0.20', desc: '⑫ 重排置信度阈值，低于则走常识兜底' },
  { key: 'rag.reflection_threshold', default: '0.4', desc: '⑮ 自纠错审查分数阈值，低于则重生成一次' },
]
</script>

<style scoped>
.config-page {
  padding: 20px;
  height: 100%;
  overflow-y: auto;
}
.sub {
  color: #606266;
  font-size: 13px;
  margin-bottom: 16px;
  line-height: 1.7;
}
code {
  background: #f0f2f5;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
}
</style>
