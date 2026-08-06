"""文本清洗：页眉页脚去重 / 空行压缩 / 规范换行"""
import re

_LINE_START_PAGE_NO = re.compile(r"^\s*[-—–]?\s*第?\s*\d+\s*页?\s*[-—–]?\s*$")  # 纯页码行


def clean_text(text: str) -> str:
    """清洗解析出的文本：
    1. 去掉纯页码行
    2. 连续重复行（页眉/页脚特征）只保留一次
    3. 压缩多余空行
    4. 统一换行为 \n
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: list[str] = []
    prev: str | None = None
    for line in lines:
        stripped = line.strip()
        if _LINE_START_PAGE_NO.match(stripped):
            continue
        # 连续重复行（页眉页脚）去重
        if stripped and stripped == prev:
            continue
        cleaned.append(line)
        prev = stripped
    out = "\n".join(cleaned)
    # 压缩 2 个以上空行
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()
