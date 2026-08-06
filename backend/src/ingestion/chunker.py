"""Markdown 感知分块：按标题层级切分并跟踪 heading_path / section_title
（⑤直读与来源标注依赖章节信息）
"""
import logging
import re

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.utils.text_normalizer import estimate_tokens

logger = logging.getLogger(__name__)

# 中文分隔符（延续旧原型 config_data.py 的配置）
SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def chunk_markdown(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[dict]:
    """按标题切分并分块，返回 [{chunk_index, content, section_title, heading_path, token_count}]"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=SEPARATORS,
    )

    # 1. 按标题行切段（保留标题到内容）
    segments: list[tuple[list[str], str]] = []  # (heading_stack, body)
    current_stack: list[str] = []

    lines = text.split("\n")
    buf: list[str] = []
    for line in lines:
        m = HEADING_RE.match(line.strip())
        if m:
            # 上一段收尾
            if buf:
                segments.append((list(current_stack), "\n".join(buf)))
                buf = []
            # 更新标题栈：同级覆盖，低级别回退
            level = len(m.group(1))
            title = m.group(2).strip()
            current_stack = [t for t in current_stack if current_stack.index(t) < level - 1]
            # 简化处理：按标题层级直接重建栈（至多为 6 级）
            current_stack = _rebuild_stack(current_stack, level, title)
        else:
            buf.append(line)
    if buf:
        segments.append((list(current_stack), "\n".join(buf)))

    # 2. 每段按长度分块，附带章节上下文
    chunks: list[dict] = []
    for stack, body in segments:
        body = body.strip()
        if not body:
            continue
        if len(body) <= chunk_size:
            pieces = [body]
        else:
            pieces = splitter.split_text(body)
        for piece in pieces:
            if not piece.strip():
                continue
            chunks.append(
                {
                    "content": piece.strip(),
                    "section_title": stack[-1] if stack else None,
                    "heading_path": " > ".join(stack) if stack else None,
                    "token_count": estimate_tokens(piece),
                }
            )

    # 3. 编索引
    for idx, c in enumerate(chunks):
        c["chunk_index"] = idx
    logger.info("分块完成：%d 段 → %d 片", len(segments), len(chunks))
    return chunks


def _rebuild_stack(current_stack: list[str], level: int, title: str) -> list[str]:
    """标题栈重建：level 层之前的保留，level 层替换为新标题，更深层清空"""
    keep = current_stack[: level - 1]
    keep.append(title)
    return keep
