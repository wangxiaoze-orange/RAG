# RAG 知识问答系统（生产级，前后端分离）

基于 **LangGraph + FastAPI + Milvus + Vue3** 的企业级 RAG 系统。严格实现 16 步聊天流水线（含缓存防穿透、分层意图识别、ReAct 多工具检索、RRF 融合、Cross-Encoder 重排、自纠错审查），配套 MinerU 文档清洗入库、JWT 登录、多模型供应商管理（qwen / deepseek / 硅基流动 / vLLM / Ollama）、MCP 双模式检索工具。

## 架构

```
┌─────────────┐   SSE /api/v2/chat/stream    ┌──────────────────────────────┐
│ Vue3 前端    │ ───────────────────────────▶ │ FastAPI + LangGraph 流水线    │
│ (Vite 5173) │ ◀─────────────────────────── │ ①会话→②缓存→③概览→意图→④改写   │
└─────────────┘   Named Events(token/stage)  │ ⑤直读→⑥记忆→⑦ReAct检索→⑧合并 │
                                             │ ⑨RRF→⑩重排→⑪压缩→⑫安全→⑬组装 │
                                             │ ⑭流式生成→⑮自纠错→⑯收尾        │
                                             └───┬────┬────┬────┬────┬──────┘
                                    redis/MySQL │    │    │    │    │
                                (缓存/记忆/元数据) etcd (配置) MinIO (文件) Milvus (向量)
```

- **中间件**：Docker Compose 一键拉起（redis / MySQL / MinIO / etcd / Milvus 2.5.4 独立模式）
- **检索工具双模式**：进程内 LangChain 工具（ReAct 使用）+ FastMCP 独立服务端（外部 MCP 客户端可调）
- **配置中心三级降级**：etcd → MySQL `rag_config` → 本地默认值（10s TTL 缓存）

## 16 步聊天流水线（POST /api/v2/chat/stream，SSE）

| # | 步骤 | 说明 |
|---|------|------|
| ① | 会话管理 | conversationId 复用/创建，标题=问题前 20 字，历史 3 轮入上下文 |
| ② | 缓存检查 | 问题归一化 → Redis freq 计数；freq≥3 且命中 → 分块模拟流式回放（防穿透） |
| ③ | 概览短路 | 正则识别「知识库里有什么」→ 查 MySQL 真实文档清单喂 LLM，不检索 |
| ④ | 查询改写 | LLM 结合历史改写为检索友好提问（闲聊/直读不改写） |
| ⑤ | 文档直读 | 勾选文档+摘要词 → 预算 18 片/每文档 max(4, 18/数) 均匀抽样 |
| ⑥ | 显式记忆 | 正则抽「我喜欢X/我对X过敏/叫我X」→ Redis 30 天 |
| ⑦ | 检索双路径 | 主：ReAct LLM 4 工具（doc_search/keyword_search/web_search/recall_memory）；降级：QueryRouter 规则直调 |
| ⑧ | 多路合并 | 各路召回规整为列表（web/memory 转 pseudo-chunk） |
| ⑨ | RRF 融合 | k=60，去重取 top15（直读路径用顺序分） |
| ⑩ | 语义重排 | 硅基流动 bge-reranker-v2-m3，候选不足也调（拿真实语义分数定置信度） |
| ⑪ | 上下文压缩 | 3000 token 预算 |
| ⑫ | SafetyGuard | 紧急词→追加急救提示；置信度<阈值→常识兜底 Prompt（明确告知通用知识） |
| ⑬ | Prompt 组装 | 角色+画像+长期记忆+参考来源[1][2][3]（文档名/章节/页码）+历史+问题 |
| ⑭ | 流式生成 | SSE token 事件逐段下发 |
| ⑮ | 自纠错审查 | 一致性/完整性评分，<0.4 携带意见重生成一次 |
| ⑯ | 收尾 | 高频问题写缓存；qa_message 持久化（答案/来源/推理链/工具日志/审查日志）；done 事件 |

**分层意图识别**：Layer1 规则锁定检索范围（kb/chat/web/mixed/direct）→ Layer2 LLM 多标签（need_vector/need_bm25/need_web/need_memory…）→ Layer3 代码策略合并（标签→工具权重表加权投票）→ 子问题拆解。

## 目录结构

```
├── docker-compose.yml          # 中间件：redis/mysql/minio/etcd/milvus
├── .env.example                # 环境变量模板（复制为 .env）
├── deploy/
│   ├── mysql/init/01_schema.sql # 11 张表 DDL（自动挂载初始化）
│   └── etcd/seed-config.sh      # etcd 种子：rag.* 参数 + 5 个内置供应商
├── backend/
│   ├── requirements.txt         # 核心依赖；requirements-mineru.txt（可选 MinerU）
│   └── src/
│       ├── main.py              # FastAPI 入口（:8000）
│       ├── config/              # 配置中心（etcd→MySQL→默认值 三级降级）
│       ├── core/                # JWT/bcrypt、SSE、MinIO、日志
│       ├── db/                  # SQLAlchemy 2.0 async ORM（11 张表）
│       ├── providers/           # 供应商抽象（OpenAI 兼容 + Fernet 密钥加密）
│       ├── rag/                 # ★ 16 步流水线（nodes/ 图节点 + services/ + prompts/）
│       │   ├── graph.py         # LangGraph 拓扑 + AgentTrace 节点埋点
│       │   ├── tools/           # 检索工具集（进程内 + MCP 双模式）
│       │   └── services/        # 缓存/重排/压缩/安全/记忆/BM25/向量
│       ├── ingestion/           # MinerU→pypdf→pdfplumber 清洗链（默认进程内 inline，可切 arq 队列）
│       └── scripts/             # init_db.py / seed_etcd.py 初始化脚本
└── frontend/
    └── src/                     # Vue3+Element Plus：登录/聊天/知识库/供应商
```

## 快速启动

### 前置要求

- Docker Desktop（含 docker compose）
- Python 3.11+
- Node.js 18+（前端已含 node_modules，无需安装）

### 步骤 1：启动中间件

```bash
# ①（中国大陆网络必须）配置 Docker 镜像加速：
#   Docker Desktop → Settings → Docker Engine → 添加 registry-mirrors：
#   ["https://dockerproxy.net","https://docker.1ms.run"] → Apply & Restart
# 验证：docker pull dockerproxy.net/redis:7.4-alpine 能拉到即可

docker compose up -d
# 等待约 1-2 分钟（etcd-init 会等 etcd 就绪后写入种子配置）
docker compose ps   # 全部 healthy 后继续
```

启动内容：`redis:7.4`、`mysql:8.0`（自动执行 01_schema.sql 建 11 张表）、`minio`（9000/9001）、`etcd:3.5`（2379）+ 种子脚本、`milvus-standalone:2.5.4`（19530）。

> 注意：Milvus 内部自带一套 etcd/minio（与业务那套隔离），网络内存占用较高（约 3-4GB），请保证 Docker 内存 ≥ 8GB。

### 步骤 2：初始化后端环境

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
# 可选（MinerU 高精度文档清洗，重依赖 ~2GB）：
# pip install -r requirements-mineru.txt
# 不装也不影响：入库自动降级 pypdf → pdfplumber

# 初始化数据库（幂等）：建表 + admin 账号 + 内置供应商入 MySQL
python -m src.scripts.init_db
# 等 Docker 中间件就绪后执行；若 etcd 不可用会自动跳过供应商种子（不报错）
```

### 步骤 3：启动后端

```bash
cd backend
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
# 验证：
#   curl http://127.0.0.1:8000/health   → {"status":"ok",...}
```

可选：启动独立 MCP 服务端（供外部 MCP 客户端调用检索工具）：

```bash
python -m src.rag.tools.mcp_server   # streamable-http，端口 8901
```

### 步骤 4：启动前端

```bash
cd frontend
npm run dev    # http://localhost:5173（/api 已代理到后端 8000）
```

### 步骤 5：首次使用（浏览器）

1. **注册/登录**（seed admin：`admin / admin123`）
2. **模型供应商** → 编辑硅基流动（siliconflow）填入你的 API Key → 「测试」连通 → 确认「设为默认」；也可新增 qwen/deepseek/vLLM/Ollama
   - 默认内置 5 个供应商模板，仅需填 Key
   - 重排与向量检索依赖嵌入模型：建议保留硅基流动的 `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3`
3. **知识库** → 新建 → 上传 PDF/Word/Markdown/TXT → 等文档状态变「就绪」（默认 uvicorn 进程内后台解析；`.env` 设 `INGESTION_MODE=arq` 时改投 Redis 队列由独立 worker 消费。管线：MinerU 清洗→分块→嵌入→写 Milvus）
4. **对话** → 勾选知识库 → 提问。可观察右侧思考面板：阶段进度/意图标签/工具调用/审查结果

## 端到端验证清单

| 场景 | 操作 | 预期 |
|------|------|------|
| 标准问答 | 提问知识库内容 | token 流式 + 来源[1][2][3]（文档名/章节/页码）+ 置信度 |
| 概览短路 | 问「我的知识库里有什么」 | 不检索直接列真实文档清单 |
| 缓存回放 | 同一问题连问 4 次 | 第 4 次起走 cache_hit 回放（freq≥3 防穿透） |
| 常识兜底 | 问知识库外内容 | 明确提示「基于通用知识」，retrieval_hit=false |
| 紧急词 | 问「火灾怎么办」 | 答案尾部追加急救提示 |
| 文档直读 | 勾选知识库 + 问「总结一下」 | path_type=document_scope，均匀抽样 |
| 记忆 | 说「我喜欢简洁回答」再提问 | 抽取记忆事件 + 后续回答体现风格 |
| 降级路由 | 关闭 rag.feature.agent_retrieval_enabled | 走规则路由检索（retrieval_source=router） |
| MCP | 外部 MCP 客户端连 8901 | doc_search/keyword_search/web_search/recall_memory 可调 |

## 配置中心（etcd，10s 生效）

| 键 | 默认 | 说明 |
|----|------|------|
| `rag.cache_freq_threshold` | 3 | ② 缓存读阈值（防穿透） |
| `rag.cache_write_min_freq` | 3 | ⑯ 缓存写阈值 |
| `rag.cache_ttl_seconds` | 604800 | 缓存 TTL（7 天） |
| `rag.document_scope_chunk_budget` | 18 | ⑤ 直读预算 |
| `rag.rrf_top_k` | 15 | ⑨ RRF Top N |
| `rag.rerank_top_n` | 6 | ⑩ 重排 Top N |
| `rag.compress_budget_tokens` | 3000 | ⑪ 压缩预算 |
| `rag.confidence_threshold` | 0.20 | ⑫ 置信度阈值（bge-reranker sigmoid 分相关内容常在 0.2~0.35，勿设 0.35） |
| `rag.reflection_threshold` | 0.4 | ⑮ 审查阈值 |
| `rag.memory_ttl_days` | 30 | ⑥ 记忆 TTL |
| `rag.feature.cache_enabled` | true | 特征开关：缓存 |
| `rag.feature.web_search_enabled` | true | 特征开关：网页检索 |
| `rag.feature.agent_retrieval_enabled` | true | 特征开关：ReAct 主路径 |

修改：`docker exec -it rag-etcd etcdctl put /config/rag/cache_freq_threshold 5`（点号键 `rag.xxx` 对应 etcd 层级 `/config/rag/xxx`）。

## API 一览（/api/v2）

- `POST /auth/register|login`、`GET /auth/me` — JWT
- `POST /chat/stream` — SSE 流式问答（Named Events：session/stage/tool_call/token/cache_hit/memory/intent/review/error/done）
- `GET|POST /kb`、`PUT|DELETE /kb/{id}`、`GET /kb/{id}/documents`、`POST /kb/{id}/documents`（上传）、`DELETE /documents/{id}`、`POST /documents/{id}/retry`、`GET /kb/{id}/chunks`
- `GET|POST /providers`、`PUT|DELETE /providers/{name}`、`POST /providers/{name}/default|test`
- `GET /conversations`、`GET /conversations/{id}/messages`、`DELETE /conversations/{id}`

## 生产部署建议

1. **数据库**：mysql 挂载卷持久化；`docker compose down` 不删数据（named volumes）
2. **后端容器化**：`backend/Dockerfile`（uvicorn --workers 4）；SSE 端点前挂 nginx 需 `proxy_buffering off`（已响应头 X-Accel-Buffering: no）
3. **入库队列**：默认 uvicorn 进程内解析（inline，部署即用）；高并发/重解析可在 `.env` 设 `INGESTION_MODE=arq` 并独立启动 worker `python -m src.ingestion.worker`（redis 做队列，compose 可拆为独立服务）
4. **密钥**：.env 的 `SECRET_KEY` 生产必须更换（Fernet 派生源）；JWT 过期 1440min 可在 .env 调
5. **安全**：api_key 在 etcd 明文（受信内网）、MySQL 侧 Fernet 加密；对外暴露需加 HTTPS 与限流

## 故障排查

后端日志自带了定位检索链路的决定性日志行，按顺序排查：

```
聊天请求: user=… kb_ids=[2] …                                   ← 请求实际选了哪个库
ReAct 检索完成: 各工具命中 {'doc_search': 10, 'keyword_search': 10} ← 工具真召回多少
RRF 融合: routes=2 candidates=… top=…                          ← 多路召回是否进入融合
重排定稿: 候选=… confidence=… threshold=… retrieval_hit=… degraded=… ← 置信度判定
```

| 症状 | 原因 | 处理 |
|------|------|------|
| 工具卡片显示命中，但回答走常识兜底 | ① 实际阈值被 etcd/MySQL 覆盖（代码默认值不生效） | 查「重排定稿」行的 `threshold` 实际值；`config_center.set('rag.confidence_threshold', '0.20')` 双写覆盖 |
| 同上 | ② 重排置信度判得过严（bge-reranker sigmoid 分相关内容常在 0.2~0.35） | 阈值设 0.20 而非 0.35 |
| 「RRF 融合: 无任何召回路」但工具明明命中 | ③ 节点返回键未在 `ChatState` 声明 → 被 LangGraph 静默丢弃 | 节点 return 的每个键都必须在 `src/rag/state.py` 声明（如 `recalls`、`system_prompt`） |
| 参考来源[1][2][3]有显示，但模型说「文档没有相关内容」 | ④ 参考来源渲染只拼了文档名没拼正文 | `_render_references` 必须把切片 `content` 拼进 prompt |
| 文档一直「待解析」 | ⑤ arq 模式没起 worker | 默认 `INGESTION_MODE=inline` 进程内解析；改 arq 需另起 `python -m src.ingestion.worker` |
| Milvus 报 `page_number` 类型错误 | ⑥ INT64 标量字段不接受 None | `insert_chunks` 会把空页码规范化为 0（已内置） |
| 向量检索静默返回空、日志只有「Milvus 检索失败」 | ⑦ 主键 `"doc_序号"` 是字符串，`int()` 转换会抛异常被宽泛 try/except 吞掉 | chunk_id 一律按 str 处理（已内置） |

## 已知边界（v1）

- Neo4j 知识图谱预留扩展点，v1 未纳入（retrieval 层可插）
- 网页检索用 DuckDuckGo（ddgs），内网环境需自行替换
- 记忆抽取仅支持 5 类显式模式（偏好/反感/过敏/风格/称呼），隐式记忆留待 v2
