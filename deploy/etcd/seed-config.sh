#!/bin/sh
# etcd 配置种子脚本（由 docker compose 的 etcd-init 一次性容器执行）
# 写入 rag.* 可调参数与默认模型供应商配置
# 键格式与代码一致：代码用 rag.xxx.yyy，etcd 键为 /config/rag/xxx/yyy
#
# 注意：quay.io/coreos/etcd 官方镜像（含 3.4.x/3.5.x）均为 distroless，无 /bin/sh，
# 无法在其内部执行脚本；故本容器使用 alpine 镜像，通过 etcd v3
# gRPC-gateway HTTP API（key/value 按协议 base64）写入，不依赖 etcdctl。
set -e

ETCD_ENDPOINT="${ETCD_ENDPOINTS:-http://etcd:2379}"

b64() { printf '%s' "$1" | base64 | tr -d '\n'; }

# 已存在的 key 不覆盖（用户改过的保留），首启写入
put_config() {
  key="$1"
  value="$2"
  k=$(b64 "$key")
  existed=$(wget -q -O - --post-data "{\"key\":\"$k\",\"limit\":1}" \
    --header 'Content-Type: application/json' \
    "$ETCD_ENDPOINT/v3/kv/range" 2>/dev/null | grep -c '"kvs"') || true
  if [ "$existed" -gt 0 ]; then
    echo "跳过（已存在）$key"
    return
  fi
  v=$(b64 "$value")
  wget -q -O /dev/null --post-data "{\"key\":\"$k\",\"value\":\"$v\"}" \
    --header 'Content-Type: application/json' \
    "$ETCD_ENDPOINT/v3/kv/put"
  echo "写入 $key = $value"
}

echo "==> 等待 etcd 就绪..."
until wget -q -O /dev/null "$ETCD_ENDPOINT/health"; do sleep 1; done

# ---------- rag.* 可调参数 ----------
put_config /config/rag/cache_freq_threshold 3             # ②缓存阈值：问题被查 ≥3 次才读缓存（防穿透）
put_config /config/rag/cache_write_min_freq 3             # ⑯高频问题累计 ≥3 次才写缓存
put_config /config/rag/cache_ttl_seconds 604800           # 缓存答案 TTL（7 天）
put_config /config/rag/document_scope_chunk_budget 18     # ⑤文档直读切片总预算（每文档至少 4 片）
put_config /config/rag/rrf_top_k 15                       # ⑨RRF 融合取 top
put_config /config/rag/rerank_top_n 6                     # ⑩重排取 top（候选不足也调，拿真实语义分数）
put_config /config/rag/compress_budget_tokens 3000        # ⑪上下文压缩 token 预算
put_config /config/rag/confidence_threshold 0.20          # ⑫置信度阈值（低于→常识兜底，明确告知通用知识；bge-reranker sigmoid 分相关内容常在 0.2~0.35，勿设 0.35）
put_config /config/rag/reflection_threshold 0.4           # ⑮自纠错审查分数阈值（低于→重生成一次）
put_config /config/rag/memory_ttl_days 30                 # ⑥显式记忆 TTL
put_config /config/rag/web_search_timeout_seconds 8       # web 检索超时
put_config /config/rag/feature/cache_enabled true         # 特征开关：缓存回放
put_config /config/rag/feature/web_search_enabled true    # 特征开关：web 检索
put_config /config/rag/feature/agent_retrieval_enabled true # 特征开关：LLM 工具检索主路径

# ---------- 默认供应商种子（OpenAI 兼容） ----------
# 用户在前端配置页覆盖；api_key 留空，由前端填写
put_config /config/providers/siliconflow '{"name":"硅基流动","provider_type":"siliconflow","base_url":"https://api.siliconflow.cn/v1","api_key":"","model":"Qwen/Qwen2.5-7B-Instruct","embedding_model":"BAAI/bge-m3","rerank_model":"BAAI/bge-reranker-v2-m3","is_default":true,"enabled":true}'
put_config /config/providers/qwen '{"name":"通义千问","provider_type":"qwen","base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1","api_key":"","model":"qwen-plus","embedding_model":"text-embedding-v3","rerank_model":"","is_default":false,"enabled":true}'
put_config /config/providers/deepseek '{"name":"DeepSeek","provider_type":"deepseek","base_url":"https://api.deepseek.com/v1","api_key":"","model":"deepseek-chat","embedding_model":"","rerank_model":"","is_default":false,"enabled":true}'
put_config /config/providers/vllm '{"name":"vLLM 本地","provider_type":"vllm","base_url":"http://host.docker.internal:8000/v1","api_key":"EMPTY","model":"Qwen2.5-7B-Instruct","embedding_model":"","rerank_model":"","is_default":false,"enabled":true}'
put_config /config/providers/ollama '{"name":"Ollama 本地","provider_type":"ollama","base_url":"http://host.docker.internal:11434/v1","api_key":"ollama","model":"qwen2.5:7b","embedding_model":"","rerank_model":"","is_default":false,"enabled":true}'

# ---------- 校验 ----------
count=$(wget -q -O - --post-data "{\"key\":\"$(b64 /config)\",\"range_end\":\"$(b64 /config0)\",\"limit\":100}" \
  --header 'Content-Type: application/json' \
  "$ETCD_ENDPOINT/v3/kv/range" | grep -o '"kvs"' | wc -l) || true
echo "==> 种子写入完成，/config 下共 $count 组配置，校验通过"
