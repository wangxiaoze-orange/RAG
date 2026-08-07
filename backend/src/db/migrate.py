"""轻量幂等迁移：为已有库补齐新增列（create_all 只建新表，不会 ALTER 旧表）
通过 information_schema 判断列是否存在，缺则 ADD COLUMN，可重复执行
"""
import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

# (表名, 列名, ADD COLUMN 定义)
_ENSURE_COLUMNS: list[tuple[str, str, str]] = [
    ("user", "role", "role VARCHAR(16) NOT NULL DEFAULT 'user' COMMENT 'admin/user'"),
    ("user", "department_id", "department_id BIGINT UNSIGNED DEFAULT NULL COMMENT '所属部门（审批通过后写入）'"),
    ("kb_knowledge_base", "chunk_strategy", "chunk_strategy VARCHAR(32) NOT NULL DEFAULT 'markdown' COMMENT 'markdown/fixed/semantic/parent_child'"),
    ("kb_knowledge_base", "chunk_size", "chunk_size INT NOT NULL DEFAULT 512"),
    ("kb_knowledge_base", "chunk_overlap", "chunk_overlap INT NOT NULL DEFAULT 50"),
    ("kb_knowledge_base", "parse_pref", "parse_pref VARCHAR(32) NOT NULL DEFAULT 'auto' COMMENT 'auto/mineru/pypdf/pdfplumber/docx/text'"),
    ("kb_knowledge_base", "parse_min_confidence", "parse_min_confidence DECIMAL(4,3) NOT NULL DEFAULT 0.5 COMMENT '解析块置信度下限（MinerU）'"),
    ("kb_document", "parse_confidence", "parse_confidence DECIMAL(4,3) DEFAULT NULL COMMENT '解析平均置信度'"),
    ("kb_chunk", "parent_id", "parent_id BIGINT UNSIGNED DEFAULT NULL COMMENT '父子切片：所属父块 id'"),
    ("kb_chunk", "is_parent", "is_parent TINYINT NOT NULL DEFAULT 0 COMMENT '1=父块（不参与向量检索）'"),
]


async def ensure_columns(conn) -> int:
    """对连接逐列检查并补齐，返回新增列数"""
    added = 0
    for table, column, ddl in _ENSURE_COLUMNS:
        row = (
            await conn.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
                ),
                {"t": table, "c": column},
            )
        ).scalar()
        if row:
            continue
        await conn.execute(text(f"ALTER TABLE `{table}` ADD COLUMN {ddl}"))
        added += 1
        logger.info("迁移：%s.%s 已补齐", table, column)
    return added
