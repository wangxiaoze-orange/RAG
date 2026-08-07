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


# ============ 固定长度切分 ============
def chunk_fixed(
    text: str,
    chunk_size: int = 512,
    chunk_overlap: int = 50,
) -> list[dict]:
    """纯定长递归切分（不感知标题），返回结构与 chunk_markdown 一致"""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=SEPARATORS,
    )
    chunks = []
    for idx, piece in enumerate(splitter.split_text(text)):
        if not piece.strip():
            continue
        chunks.append({
            "chunk_index": idx,
            "content": piece.strip(),
            "section_title": None,
            "heading_path": None,
            "token_count": estimate_tokens(piece),
        })
    # 编索引（跳过空片后重排）
    for i, c in enumerate(chunks):
        c["chunk_index"] = i
    logger.info("固定切分完成：%d 片", len(chunks))
    return chunks


# ============ 父子切片 ============
PARENT_SIZE_MULTIPLIER = 4  # 父块默认 = 4 × 子块长度


def chunk_parent_child(
    text: str,
    child_size: int = 256,
    child_overlap: int = 40,
    parent_size: int | None = None,
) -> tuple[list[dict], list[dict]]:
    """父子切分：大块（父）提供上下文，小块（子）参与向量检索
    返回 (children, parents)：
    - children: [{chunk_index, content, section_title, heading_path, token_count, parent_index}]
    - parents:  [{index, content}]（先落库拿 id，再回填 children 的 parent_id）
    """
    parent_size = parent_size or child_size * PARENT_SIZE_MULTIPLIER
    parents: list[dict] = []
    children: list[dict] = []

    parent_splitter = RecursiveCharacterTextSplitter(
        chunk_size=parent_size, chunk_overlap=child_overlap, length_function=len, separators=SEPARATORS,
    )
    child_splitter = RecursiveCharacterTextSplitter(
        chunk_size=child_size, chunk_overlap=child_overlap, length_function=len, separators=SEPARATORS,
    )

    for p_idx, parent_piece in enumerate(parent_splitter.split_text(text)):
        parent_piece = parent_piece.strip()
        if not parent_piece:
            continue
        parents.append({"index": p_idx, "content": parent_piece})
        for child_piece in child_splitter.split_text(parent_piece):
            child_piece = child_piece.strip()
            if not child_piece:
                continue
            children.append({
                "content": child_piece,
                "section_title": None,
                "heading_path": None,
                "token_count": estimate_tokens(child_piece),
                "parent_index": p_idx,
            })

    for i, c in enumerate(children):
        c["chunk_index"] = i
    logger.info("父子切分完成：%d 父块 → %d 子块", len(parents), len(children))
    return children, parents
