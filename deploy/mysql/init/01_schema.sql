-- RAG 系统数据库 DDL（由 mysql 容器首次启动时自动执行）
-- 字符集：utf8mb4；表注释对齐聊天流水线 ①-⑯ 各环节
USE rag;

-- ============ 用户表（JWT 登录） ============
CREATE TABLE IF NOT EXISTS `user` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `username`      VARCHAR(64)  NOT NULL COMMENT '登录名',
  `password_hash` VARCHAR(128) NOT NULL COMMENT 'bcrypt 哈希',
  `nickname`      VARCHAR(64)  DEFAULT NULL COMMENT '昵称',
  `email`         VARCHAR(128) DEFAULT NULL COMMENT '邮箱',
  `status`        TINYINT      NOT NULL DEFAULT 1 COMMENT '1启用 0禁用',
  `last_login_at` DATETIME     DEFAULT NULL COMMENT '最后登录时间',
  `created_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户表';

-- ============ 会话表（①会话管理） ============
CREATE TABLE IF NOT EXISTS `qa_conversation` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`         BIGINT UNSIGNED NOT NULL COMMENT '所属用户',
  `title`           VARCHAR(100) NOT NULL COMMENT '标题=首问前20字',
  `provider_id`     BIGINT UNSIGNED DEFAULT NULL COMMENT '使用的供应商',
  `model_name`      VARCHAR(128)   DEFAULT NULL COMMENT '使用的模型',
  `kb_ids`          JSON DEFAULT NULL COMMENT '会话默认知识库范围 [1,2]',
  `message_count`   INT NOT NULL DEFAULT 0 COMMENT '消息条数',
  `last_message_at` DATETIME DEFAULT NULL COMMENT '最后消息时间',
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_last` (`user_id`, `last_message_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='问答会话表';

-- ============ 消息表（核心，承载缓存/置信度/推理链落库） ============
CREATE TABLE IF NOT EXISTS `qa_message` (
  `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `conversation_id`    BIGINT UNSIGNED NOT NULL COMMENT '所属会话',
  `user_id`            BIGINT UNSIGNED NOT NULL COMMENT '所属用户',
  `role`               VARCHAR(16) NOT NULL COMMENT 'user/assistant',
  `content`            MEDIUMTEXT  NOT NULL COMMENT '消息正文',
  -- 缓存相关（②）
  `question_normalized` VARCHAR(512) DEFAULT NULL COMMENT '归一化问题（缓存键）',
  `freq`               INT NOT NULL DEFAULT 1 COMMENT '标准化问题累计被查次数',
  `cache_hit`          TINYINT NOT NULL DEFAULT 0 COMMENT '本次是否命中缓存回放',
  `cache_written`      TINYINT NOT NULL DEFAULT 0 COMMENT '答案是否已写缓存',
  -- 流程标记
  `path_type`          VARCHAR(32) NOT NULL DEFAULT 'standard' COMMENT 'standard/overview/document_scope/cache_replay/fallback',
  `confidence`         DECIMAL(5,4) DEFAULT NULL COMMENT '⑫重排最高 rerankScore',
  `retrieval_hit`      TINYINT NOT NULL DEFAULT 1 COMMENT '置信度是否过阈值',
  `intent_scope`       VARCHAR(32) DEFAULT NULL COMMENT '分层第一层意图',
  `intent_labels`      JSON DEFAULT NULL COMMENT '多标签意图',
  `sources`            JSON DEFAULT NULL COMMENT '来源引用[{doc_name,chapter,page,score}]',
  `agent_trace`        JSON DEFAULT NULL COMMENT 'Agent 推理链',
  `tool_calls`         JSON DEFAULT NULL COMMENT '工具调用日志快照',
  `reflection`         JSON DEFAULT NULL COMMENT '自纠错审查结论',
  `latency_ms`         INT DEFAULT NULL COMMENT '总耗时',
  `error_code`         VARCHAR(32) DEFAULT NULL COMMENT '错误码',
  `created_at`         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_conv_id` (`conversation_id`, `id`),
  KEY `idx_user_conv` (`user_id`, `conversation_id`),
  KEY `idx_normalized` (`question_normalized`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='问答消息表';

-- ============ 知识库表（③概览短路读取） ============
CREATE TABLE IF NOT EXISTS `kb_knowledge_base` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`        VARCHAR(128) NOT NULL COMMENT '知识库名称',
  `description` VARCHAR(512) DEFAULT NULL COMMENT '描述',
  `owner_id`    BIGINT UNSIGNED NOT NULL COMMENT '创建人',
  `doc_count`   INT NOT NULL DEFAULT 0 COMMENT '文档数',
  `chunk_count` INT NOT NULL DEFAULT 0 COMMENT '切片总数',
  `status`      TINYINT NOT NULL DEFAULT 1 COMMENT '1启用 0停用',
  `created_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_owner` (`owner_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库表';

-- ============ 文档表（MinIO 原文件 + 解析状态机） ============
CREATE TABLE IF NOT EXISTS `kb_document` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `kb_id`          BIGINT UNSIGNED NOT NULL COMMENT '所属知识库',
  `filename`       VARCHAR(255) NOT NULL COMMENT '原始文件名',
  `file_type`      VARCHAR(32) NOT NULL COMMENT 'pdf/docx/md/txt/png/jpg',
  `size_bytes`     BIGINT NOT NULL DEFAULT 0,
  `md5`            CHAR(32) NOT NULL COMMENT '内容去重',
  `minio_object`   VARCHAR(255) NOT NULL COMMENT 'MinIO 对象键 kb_{id}/{uuid}.ext',
  `md_object`      VARCHAR(255) DEFAULT NULL COMMENT '解析后 markdown 对象键',
  `status`         VARCHAR(16) NOT NULL DEFAULT 'uploaded'
                   COMMENT 'uploaded/parsing/cleaning/chunking/embedding/ready/failed',
  `chunk_count`    INT NOT NULL DEFAULT 0,
  `parse_pipeline` VARCHAR(32) DEFAULT NULL COMMENT 'mineru/pypdf/pdfplumber/docx/text',
  `error_msg`      VARCHAR(512) DEFAULT NULL COMMENT '失败原因',
  `created_at`     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_kb` (`kb_id`),
  KEY `idx_md5` (`md5`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库文档表';

-- ============ 切片表（⑤直读/⑨融合/来源标注数据源） ============
CREATE TABLE IF NOT EXISTS `kb_chunk` (
  `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `kb_id`        BIGINT UNSIGNED NOT NULL,
  `doc_id`       BIGINT UNSIGNED NOT NULL,
  `doc_name`     VARCHAR(255) NOT NULL COMMENT '冗余存文档名便于来源标注',
  `chunk_index`  INT NOT NULL COMMENT '文档内序号',
  `content`      MEDIUMTEXT NOT NULL COMMENT '切片文本',
  `token_count`  INT NOT NULL DEFAULT 0,
  `page_number`  INT DEFAULT NULL COMMENT 'MinerU 行级映射页码（降级解析为空）',
  `section_title` VARCHAR(255) DEFAULT NULL COMMENT '章节标题',
  `heading_path` VARCHAR(512) DEFAULT NULL COMMENT '标题层级路径 第一章>1.1>...',
  `milvus_id`    BIGINT DEFAULT NULL COMMENT 'Milvus 主键回填',
  `embedding_provider` VARCHAR(64) DEFAULT NULL COMMENT '嵌入供应商',
  `created_at`   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_doc` (`doc_id`, `chunk_index`),
  KEY `idx_kb` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库切片表';

-- ============ 模型供应商表（etcd 主存，MySQL 兜底） ============
CREATE TABLE IF NOT EXISTS `model_provider` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`            VARCHAR(64) NOT NULL COMMENT '显示名',
  `provider_type`   VARCHAR(32) NOT NULL COMMENT 'qwen/deepseek/siliconflow/vllm/ollama/custom',
  `base_url`        VARCHAR(255) NOT NULL COMMENT 'OpenAI 兼容地址',
  `api_key`         VARCHAR(512) DEFAULT NULL COMMENT 'Fernet 加密存储',
  `model`           VARCHAR(128) NOT NULL COMMENT '默认对话模型',
  `embedding_model` VARCHAR(128) DEFAULT NULL COMMENT '嵌入模型',
  `rerank_model`    VARCHAR(128) DEFAULT NULL COMMENT '重排模型',
  `extra`           JSON DEFAULT NULL COMMENT '扩展（headers 等）',
  `is_default`      TINYINT NOT NULL DEFAULT 0,
  `enabled`         TINYINT NOT NULL DEFAULT 1,
  `etcd_key`        VARCHAR(255) DEFAULT NULL COMMENT '同步的 etcd key',
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_type` (`provider_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='模型供应商表';

-- ============ 配置兜底表（etcd 不可用时读取） ============
CREATE TABLE IF NOT EXISTS `rag_config` (
  `config_key` VARCHAR(128) NOT NULL COMMENT 'rag.* 或 providers.*',
  `value`      JSON NOT NULL,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`config_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='RAG 参数兜底表';

-- ============ Agent 推理链日志（⑮⑯） ============
CREATE TABLE IF NOT EXISTS `agent_trace` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `message_id`      BIGINT UNSIGNED NOT NULL,
  `conversation_id` BIGINT UNSIGNED NOT NULL,
  `node_name`       VARCHAR(64) NOT NULL COMMENT '节点名',
  `input`           JSON DEFAULT NULL COMMENT '输入摘要',
  `output`          JSON DEFAULT NULL COMMENT '输出摘要',
  `latency_ms`      INT DEFAULT NULL,
  `status`          VARCHAR(16) DEFAULT 'ok',
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_msg` (`message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Agent推理链日志';

-- ============ 工具调用日志（⑦） ============
CREATE TABLE IF NOT EXISTS `tool_call_log` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `message_id`      BIGINT UNSIGNED NOT NULL,
  `conversation_id` BIGINT UNSIGNED NOT NULL,
  `tool_name`       VARCHAR(64) NOT NULL COMMENT 'doc_search/keyword_search/web_search/recall_memory',
  `source`          VARCHAR(16) NOT NULL COMMENT 'agent/router（降级）',
  `input`           JSON DEFAULT NULL,
  `output`          JSON DEFAULT NULL COMMENT '结果摘要（前N条）',
  `latency_ms`      INT DEFAULT NULL,
  `status`          VARCHAR(16) DEFAULT 'ok',
  `error`           VARCHAR(512) DEFAULT NULL,
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_msg` (`message_id`),
  KEY `idx_tool` (`tool_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='工具调用日志';

-- ============ 自纠错审查日志（⑮） ============
CREATE TABLE IF NOT EXISTS `self_reflection_log` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `message_id`      BIGINT UNSIGNED NOT NULL,
  `conversation_id` BIGINT UNSIGNED NOT NULL,
  `question`        TEXT,
  `answer`          MEDIUMTEXT,
  `conclusion`      VARCHAR(32) NOT NULL COMMENT 'pass/unsupported/contradiction/incomplete',
  `issues`          JSON DEFAULT NULL COMMENT '问题列表',
  `action`          VARCHAR(32) DEFAULT 'none' COMMENT 'none/rewrite/notify',
  `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_msg` (`message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='自纠错审查日志';
