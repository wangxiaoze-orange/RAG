"""ORM 模型：与 deploy/mysql/init/01_schema.sql 的 11 张表一一对应"""
import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# ============ 用户表 ============
class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="登录名")
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="bcrypt 哈希")
    nickname: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default="user", comment="admin/user")
    department_id: Mapped[int | None] = mapped_column(BigInteger, comment="所属部门（审批通过后写入）")
    status: Mapped[int] = mapped_column(Integer, default=1, comment="1启用 0禁用")
    last_login_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ============ 部门表（管理员自定义） ============
class Department(Base):
    __tablename__ = "department"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="部门名称")
    description: Mapped[str | None] = mapped_column(String(255))
    created_by: Mapped[int | None] = mapped_column(BigInteger, comment="创建人（管理员）")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ============ 入部申请表 ============
class DeptApply(Base):
    __tablename__ = "dept_apply"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", comment="pending/approved/rejected")
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger)
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)


# ============ 知识库-部门授权表 ============
class KbDepartment(Base):
    __tablename__ = "kb_department"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    department_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)


# ============ 会话表（①会话管理） ============
class QaConversation(Base):
    __tablename__ = "qa_conversation"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False, comment="标题=首问前20字")
    provider_id: Mapped[int | None] = mapped_column(BigInteger)
    model_name: Mapped[str | None] = mapped_column(String(128))
    kb_ids: Mapped[list | None] = mapped_column(JSON, comment="会话默认知识库范围")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    last_message_at: Mapped[datetime.datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ============ 消息表（核心） ============
class QaMessage(Base):
    __tablename__ = "qa_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, comment="user/assistant")
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    # 缓存相关（②）
    question_normalized: Mapped[str | None] = mapped_column(String(512), index=True)
    freq: Mapped[int] = mapped_column(Integer, default=1, comment="标准化问题累计被查次数")
    cache_hit: Mapped[int] = mapped_column(Integer, default=0)
    cache_written: Mapped[int] = mapped_column(Integer, default=0)
    # 流程标记
    path_type: Mapped[str] = mapped_column(String(32), default="standard")
    confidence: Mapped[float | None] = mapped_column(Float, comment="⑫重排最高分")
    retrieval_hit: Mapped[int] = mapped_column(Integer, default=1)
    intent_scope: Mapped[str | None] = mapped_column(String(32))
    intent_labels: Mapped[list | None] = mapped_column(JSON)
    sources: Mapped[list | None] = mapped_column(JSON)
    agent_trace: Mapped[list | None] = mapped_column(JSON)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    reflection: Mapped[dict | None] = mapped_column(JSON)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)


# ============ 知识库表（③概览短路） ============
class KbKnowledgeBase(Base):
    __tablename__ = "kb_knowledge_base"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(String(512))
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    doc_count: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=1, comment="1启用 0停用")
    # 入库配置（知识库级）
    chunk_strategy: Mapped[str] = mapped_column(String(32), default="markdown", comment="markdown/fixed/semantic/parent_child")
    chunk_size: Mapped[int] = mapped_column(Integer, default=512)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50)
    parse_pref: Mapped[str] = mapped_column(String(32), default="auto", comment="auto/mineru/pypdf/pdfplumber/docx/text")
    parse_min_confidence: Mapped[float] = mapped_column(Float, default=0.5, comment="解析块置信度下限（MinerU）")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ============ 文档表 ============
class KbDocument(Base):
    __tablename__ = "kb_document"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    md5: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="内容去重")
    minio_object: Mapped[str] = mapped_column(String(255), nullable=False)
    md_object: Mapped[str | None] = mapped_column(String(255), comment="解析后 markdown 对象键")
    status: Mapped[str] = mapped_column(String(16), default="uploaded")
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    parse_pipeline: Mapped[str | None] = mapped_column(String(32))
    parse_confidence: Mapped[float | None] = mapped_column(Float, comment="解析平均置信度")
    error_msg: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ============ 切片表 ============
class KbChunk(Base):
    __tablename__ = "kb_chunk"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    doc_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    doc_name: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str | None] = mapped_column(String(255))
    heading_path: Mapped[str | None] = mapped_column(String(512))
    milvus_id: Mapped[int | None] = mapped_column(BigInteger)
    embedding_provider: Mapped[str | None] = mapped_column(String(64))
    parent_id: Mapped[int | None] = mapped_column(BigInteger, comment="父子切片：所属父块 id")
    is_parent: Mapped[int] = mapped_column(Integer, default=0, comment="1=父块（不参与向量检索）")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)


# ============ 高频问题经验库（FAQ） ============
class QaFaq(Base):
    __tablename__ = "qa_faq"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(String(512), nullable=False, comment="原始问题")
    question_normalized: Mapped[str] = mapped_column(String(512), nullable=False, index=True, comment="归一化问题（匹配键）")
    rewritten_question: Mapped[str | None] = mapped_column(String(512), comment="改写后问题")
    answer: Mapped[str] = mapped_column(MEDIUMTEXT, nullable=False)
    sources: Mapped[list | None] = mapped_column(JSON, comment="来源引用快照")
    kb_ids: Mapped[list | None] = mapped_column(JSON, comment="适用知识库范围")
    status: Mapped[str] = mapped_column(String(16), default="pending", comment="pending/published/disabled")
    freq: Mapped[int] = mapped_column(Integer, default=1, comment="沉淀时的问题热度")
    hit_count: Mapped[int] = mapped_column(Integer, default=0, comment="发布后直读命中次数")
    expire_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, comment="有效期（空=永久）")
    created_by: Mapped[int | None] = mapped_column(BigInteger, comment="发布/创建人，自动沉淀为空")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ============ 模型供应商表（etcd 主存，MySQL 兜底） ============
class ModelProvider(Base):
    __tablename__ = "model_provider"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str | None] = mapped_column(String(512), comment="Fernet 加密")
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    embedding_model: Mapped[str | None] = mapped_column(String(128))
    rerank_model: Mapped[str | None] = mapped_column(String(128))
    extra: Mapped[dict | None] = mapped_column(JSON)
    is_default: Mapped[int] = mapped_column(Integer, default=0)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    etcd_key: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ============ 配置兜底表 ============
class RagConfig(Base):
    __tablename__ = "rag_config"

    config_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[object] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ============ Agent 推理链日志 ============
class AgentTrace(Base):
    __tablename__ = "agent_trace"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    input: Mapped[dict | None] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)


# ============ 工具调用日志 ============
class ToolCallLog(Base):
    __tablename__ = "tool_call_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False, comment="agent/router")
    input: Mapped[dict | None] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="ok")
    error: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)


# ============ 自纠错审查日志 ============
class SelfReflectionLog(Base):
    __tablename__ = "self_reflection_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    conversation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    question: Mapped[str | None] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text)
    conclusion: Mapped[str] = mapped_column(String(32), nullable=False)
    issues: Mapped[list | None] = mapped_column(JSON)
    action: Mapped[str] = mapped_column(String(32), default="none")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=_now)
