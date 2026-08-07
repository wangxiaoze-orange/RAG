from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ============ 聊天 ============
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000, description="用户问题")
    conversation_id: int | None = Field(default=None, description="复用会话，空则自动创建")
    kb_ids: list[int] = Field(default_factory=list, description="限定知识库范围，空则全部")
    provider_id: int | None = Field(default=None, description="覆盖默认供应商")
    model: str | None = Field(default=None, description="覆盖默认模型")


class ConversationOut(BaseModel):
    id: int
    title: str
    message_count: int
    last_message_at: datetime | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    path_type: str | None = None
    confidence: float | None = None
    sources: list[dict] | None = None
    reflection: dict | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============ 知识库 ============
class KbCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    chunk_strategy: str = Field(default="markdown", pattern="^(markdown|fixed|semantic|parent_child)$", description="切片策略")
    chunk_size: int = Field(default=512, ge=64, le=4096)
    chunk_overlap: int = Field(default=50, ge=0, le=512)
    parse_pref: str = Field(default="auto", pattern="^(auto|mineru|pypdf|pdfplumber|docx|text)$", description="解析器偏好")
    parse_min_confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="解析置信度下限")


class KbUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: int | None = None
    chunk_strategy: str | None = Field(default=None, pattern="^(markdown|fixed|semantic|parent_child)$")
    chunk_size: int | None = Field(default=None, ge=64, le=4096)
    chunk_overlap: int | None = Field(default=None, ge=0, le=512)
    parse_pref: str | None = Field(default=None, pattern="^(auto|mineru|pypdf|pdfplumber|docx|text)$")
    parse_min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class KbOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    doc_count: int
    chunk_count: int
    status: int
    chunk_strategy: str = "markdown"
    chunk_size: int = 512
    chunk_overlap: int = 50
    parse_pref: str = "auto"
    parse_min_confidence: float = 0.5
    is_owner: bool = False
    department_names: list[str] = []
    created_at: datetime

    class Config:
        from_attributes = True


class KbDepartmentsIn(BaseModel):
    department_ids: list[int] = Field(default_factory=list)


class DocumentOut(BaseModel):
    id: int
    kb_id: int
    filename: str
    file_type: str
    size_bytes: int
    status: str
    chunk_count: int
    parse_pipeline: str | None = None
    error_msg: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ChunkOut(BaseModel):
    id: int
    doc_id: int
    doc_name: str
    chunk_index: int
    content: str
    page_number: int | None = None
    section_title: str | None = None
    heading_path: str | None = None

    class Config:
        from_attributes = True
