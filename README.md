# RAG 知识问答系统（生产级，前后端分离）

基于 **LangGraph + FastAPI + Milvus + Vue3** 的企业级 RAG 系统。严格实现 16 步聊天流水线（含 FAQ 经验库直读、缓存防穿透、分层意图识别（多标签置信度加权召回）、ReAct 多工具检索、RRF 融合、Cross-Encoder 重排、自纠错审查），配套 MinerU 文档清洗入库（知识库级切片策略与解析置信度过滤）、JWT 登录与部门权限体系（注册选部门→管理员审批→知识库按部门授权）、高频问题经验库、流水线参数前端可视化配置、多模型供应商管理（qwen / deepseek / 硅基流动 / vLLM / Ollama）、MCP 双模式检索工具。

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
| ② | 缓存检查 | 先查 FAQ 经验库（已发布且未过期，归一化精确匹配 → 命中直接回放 path_type=faq，不检索不生成）；再走 Redis freq 计数，freq≥3 且命中 → 分块模拟流式回放（防穿透） |
| ③ | 概览短路 | 正则识别「知识库里有什么」→ 查 MySQL 真实文档清单喂 LLM，不检索 |
| ④ | 查询改写 | LLM 结合历史改写为检索友好提问（闲聊/直读不改写） |
| ⑤ | 文档直读 | 勾选文档+摘要词 → 预算 18 片/每文档 max(4, 18/数) 均匀抽样 |
| ⑥ | 显式记忆 | 正则抽「我喜欢X/我对X过敏/叫我X」→ Redis 30 天 |
| ⑦ | 检索双路径 | 主：ReAct LLM 4 工具（doc_search/keyword_search/web_search/recall_memory）；降级：QueryRouter 规则直调；各工具 top_k 受意图置信度加权配额（recall_budgets）截断 |
| ⑧ | 多路合并 | 各路召回规整为列表（web/memory 转 pseudo-chunk） |
| ⑨ | RRF 融合 | k=60，去重取 top15（直读路径用顺序分） |
| ⑩ | 语义重排 | 硅基流动 bge-reranker-v2-m3，候选不足也调（拿真实语义分数定置信度） |
| ⑪ | 上下文压缩 | 3000 token 预算；父子切片策略下子块命中先扩展为父块全文（同父块去重保留最高分） |
| ⑫ | SafetyGuard | 紧急词→追加急救提示；置信度<阈值→常识兜底 Prompt（明确告知通用知识） |
| ⑬ | Prompt 组装 | 角色+画像+长期记忆+参考来源[1][2][3]（文档名/章节/页码）+历史+问题 |
| ⑭ | 流式生成 | SSE token 事件逐段下发 |
| ⑮ | 自纠错审查 | 一致性/完整性评分，<0.4 携带意见重生成一次 |
| ⑯ | 收尾 | 高频问题写缓存并自动沉淀经验库（freq 达标且检索命中 → FAQ 待审核条目）；qa_message 持久化（答案/来源/推理链/工具日志/审查日志）；done 事件 |

**分层意图识别**：Layer1 规则锁定检索范围（kb/chat/web/mixed/direct）→ Layer2 LLM 多标签带置信度（`[{label, confidence}]`：need_vector/need_bm25/need_web/need_memory/need_fact_check/need_summary/need_comparison）→ Layer3 代码策略合并（标签→工具权重表加权投票）+ 置信度加权召回配额（标签权重×置信度 → 归一化为各工具 top_k，总量 `rag.recall_total` 默认 20）→ 子问题拆解。

## 目录结构

```
├── docker-compose.yml          # 中间件：redis/mysql/minio/etcd/milvus
├── .env.example                # 环境变量模板（复制为 .env）
├── deploy/
│   ├── mysql/init/01_schema.sql # 15 张表 DDL（自动挂载初始化）
│   └── etcd/seed-config.sh      # etcd 种子：rag.* 参数 + 5 个内置供应商
├── backend/
│   ├── requirements.txt         # 核心依赖；requirements-mineru.txt（可选 MinerU）
│   └── src/
│       ├── main.py              # FastAPI 入口（:8000）
│       ├── config/              # 配置中心（etcd→MySQL→默认值 三级降级）
│       ├── core/                # JWT/bcrypt、SSE、MinIO、日志、权限依赖（require_admin）
│       ├── db/                  # SQLAlchemy 2.0 async ORM（15 张表）+ migrate.py 幂等补列
│       ├── providers/           # 供应商抽象（OpenAI 兼容 + Fernet 密钥加密）
│       ├── rag/                 # ★ 16 步流水线（nodes/ 图节点 + services/ + prompts/）
│       │   ├── graph.py         # LangGraph 拓扑 + AgentTrace 节点埋点
│       │   ├── tools/           # 检索工具集（进程内 + MCP 双模式，支持召回配额截断）
│       │   └── services/        # 缓存/重排/压缩/安全/记忆/BM25/向量/FAQ 存取/父块扩展
│       ├── ingestion/           # 解析链（auto/mineru/pypdf/pdfplumber，置信度过滤）+ 4 种切片策略（markdown/fixed/semantic/parent_child）
│       └── scripts/             # init_db.py / seed_etcd.py 初始化脚本
└── frontend/
    └── src/                     # Vue3+Element Plus：登录/注册选部门/聊天/知识库/供应商/用户管理/经验库/流水线配置
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

启动内容：`redis:7.4`、`mysql:8.0`（自动执行 01_schema.sql 建 15 张表）、`minio`（9000/9001）、`etcd:3.5`（2379）+ 种子脚本、`milvus-standalone:2.5.4`（19530）。

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

# 初始化数据库（幂等）：建表 + 旧库补列 + admin 账号 + 内置供应商 + 默认配置入 MySQL
python -m src.scripts.init_db
# 等 Docker 中间件就绪后执行；旧库会通过 information_schema 检查幂等补新列，无需重建数据卷
# 若 etcd 不可用会自动跳过供应商种子（不报错）
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

1. **注册/登录**（seed admin：`admin / admin123`；若系统还没有任何管理员，第一个注册的用户自动成为管理员）。注册时可选择申请加入的部门，注册后立即可用，部门待管理员审批
2. **用户管理**（仅管理员）：部门管理（自定义部门）/ 入部审批（通过/驳回）/ 用户管理（启用禁用、改角色、指派部门）
3. **模型供应商** → 编辑硅基流动（siliconflow）填入你的 API Key → 「测试」连通 → 确认「设为默认」；也可新增 qwen/deepseek/vLLM/Ollama
   - 默认内置 5 个供应商模板，仅需填 Key
   - 重排与向量检索依赖嵌入模型：建议保留硅基流动的 `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3`
4. **知识库** → 新建（可选切片策略 markdown/固定长度/语义切分/父子切片，解析器偏好与置信度下限，仅对新上传文档生效）→ 上传 PDF/Word/Markdown/TXT → 等文档状态变「就绪」（管线：解析（置信度过滤）→分块→嵌入→写 Milvus）
   - 管理员可在知识库卡片「权限设置」中勾选授权部门；普通用户只能看到自己创建的和所在部门被授权的知识库
5. **流水线配置**（仅管理员）：温度、召回总量、rerank/置信度阈值、缓存与经验库开关、意图标签权重、默认切片策略等均可在线修改，约 10 秒内生效（配置中心双写 etcd + MySQL）
6. **对话** → 勾选知识库 → 提问。可观察右侧思考面板：阶段进度/意图标签与置信度/召回配额/工具调用/审查结果
7. **经验库**：高频问题达标后自动沉淀为待审核 FAQ → 管理员在「经验库」页发布 → 再问同一问题直接命中回放（不检索不生成）；普通用户可在经验库页搜索已发布问题

## 端到端验证清单

| 场景 | 操作 | 预期 |
|------|------|------|
| 标准问答 | 提问知识库内容 | token 流式 + 来源[1][2][3]（文档名/章节/页码）+ 置信度 |
| 概览短路 | 问「我的知识库里有什么」 | 不检索直接列真实文档清单 |
| 缓存回放 | 同一问题连问 4 次 | 第 4 次起走 cache_hit 回放（freq≥3 防穿透） |
| 经验库直读 | 管理员发布 FAQ 后再问同一问题 | path_type=faq，不检索不生成，hit_count+1；设过期后失效 |
| 部门权限 | 注册选部门 → 管理员审批 → 授权 KB 给部门 | 普通用户可见该 KB；越权 kb_id 在聊天侧被过滤 |
| 配置热更新 | 配置页改温度/阈值 | 约 10 秒内生效（日志可见） |
| 切片策略 | 分别用 fixed/semantic/parent_child 建库上传文档 | 切片数合理；父子策略检索命中后上下文为父块全文 |
| 常识兜底 | 问知识库外内容 | 明确提示「基于通用知识」，retrieval_hit=false |
| 紧急词 | 问「火灾怎么办」 | 答案尾部追加急救提示 |
| 文档直读 | 勾选知识库 + 问「总结一下」 | path_type=document_scope，均匀抽样 |
| 记忆 | 说「我喜欢简洁回答」再提问 | 抽取记忆事件 + 后续回答体现风格 |
| 降级路由 | 关闭 rag.feature.agent_retrieval_enabled | 走规则路由检索（retrieval_source=router），同样受召回配额约束 |
| MCP | 外部 MCP 客户端连 8901 | doc_search/keyword_search/web_search/recall_memory 可调 |

## 配置中心（etcd，10s 生效）

管理员可直接在前端「流水线配置」页在线修改（双写 etcd + MySQL），也可用 etcdctl：

| 键 | 默认 | 说明 |
|----|------|------|
| `rag.temperature` | 0.7 | 生成温度（0 严谨 ~ 2 发散） |
| `rag.cache_freq_threshold` | 3 | ② 缓存读阈值（防穿透） |
| `rag.cache_write_min_freq` | 3 | ⑯ 缓存写/经验沉淀阈值 |
| `rag.cache_ttl_seconds` | 604800 | 缓存 TTL（7 天） |
| `rag.document_scope_chunk_budget` | 18 | ⑤ 直读预算 |
| `rag.rrf_top_k` | 15 | ⑨ RRF Top N |
| `rag.rerank_top_n` | 6 | ⑩ 重排 Top N |
| `rag.compress_budget_tokens` | 3000 | ⑪ 压缩预算 |
| `rag.confidence_threshold` | 0.20 | ⑫ 置信度阈值（bge-reranker sigmoid 分相关内容常在 0.2~0.35，勿设 0.35） |
| `rag.reflection_threshold` | 0.4 | ⑮ 审查阈值 |
| `rag.memory_ttl_days` | 30 | ⑥ 记忆 TTL |
| `rag.recall_total` | 20 | 意图置信度加权的召回片段总量，按标签权重分配给各检索路 |
| `rag.intent.label_weights` | 内置权重表 | 各意图标签权重（JSON，×标签置信度 → 各检索路召回配额占比） |
| `rag.chunk_strategy` | markdown | 默认切片策略 markdown/fixed/semantic/parent_child |
| `rag.parse_min_confidence` | 0.5 | 解析模块默认置信度下限（知识库未单独配置时用） |
| `rag.feature.cache_enabled` | true | 特征开关：缓存 |
| `rag.feature.faq_enabled` | true | 特征开关：经验库直读与自动沉淀 |
| `rag.feature.web_search_enabled` | true | 特征开关：网页检索 |
| `rag.feature.agent_retrieval_enabled` | true | 特征开关：ReAct 主路径 |

修改：`docker exec -it rag-etcd etcdctl put /config/rag/cache_freq_threshold 5`（点号键 `rag.xxx` 对应 etcd 层级 `/config/rag/xxx`）。

## API 一览（/api/v2）

- `POST /auth/register|login`、`GET /auth/me` — JWT（注册可携 `department_id` 申请入部）
- `POST /chat/stream` — SSE 流式问答（Named Events：session/stage/tool_call/token/cache_hit/memory/intent/review/error/done）；非管理员传入的越权 kb_ids 会被过滤
- `GET|POST /kb`、`PUT|DELETE /kb/{id}`、`GET /kb/{id}/documents`、`POST /kb/{id}/documents`（上传）、`DELETE /documents/{id}`、`POST /documents/{id}/retry`、`GET /kb/{id}/chunks`；KB 列表按权限过滤（admin 全部；普通用户 = 自建 + 部门授权）
- `GET|PUT /kb/{id}/departments` — 知识库授权部门（PUT 仅 admin）
- `GET /departments/public`（注册页选部门，无需登录）、`GET /my-department`
- `GET|POST|PUT|DELETE /admin/departments`、`GET /admin/users`、`PUT /admin/users/{id}/status|role|department`、`GET /admin/applications`、`POST /admin/applications/{id}/approve|reject` — 均仅 admin
- `GET /faqs?status=&q=`、`PUT /faqs/{id}`、`POST /faqs/{id}/publish|disable`、`DELETE /faqs/{id}`（admin）；`GET /faqs/search?q=`（全员，仅已发布未过期）
- `GET|PUT /admin/config` — 流水线参数读写（仅 admin，双写 etcd + MySQL）
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
- FAQ 匹配为归一化精确匹配（与缓存键一致），经验库搜索页走 LIKE 模糊搜索
- 语义切分依赖默认供应商的 embedding 接口，不可用时自动降级固定长度切分
- 旧库升级通过 `init_db` 幂等补列完成，无需重建数据卷；切片/解析配置变更仅对之后新上传的文档生效
