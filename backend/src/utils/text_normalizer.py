"""文本工具：问题归一化 / token 估算"""


def normalize_question(question: str) -> str:
    """②问题归一化（缓存键）：去空格、统一小写、全角转半角"""
    s = question.strip()
    # 全角 → 半角
    out = []
    for ch in s:
        code = ord(ch)
        if code == 0x3000:  # 全角空格
            out.append(" ")
        elif 0xFF01 <= code <= 0xFF5E:  # 全角标点/字母
            out.append(chr(code - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out).replace(" ", "").lower()


def estimate_tokens(text: str) -> int:
    """token 估算：中文约 1 字 ≈ 1 token，英文约 4 字符 ≈ 1 token
    精确计数用 tiktoken（compressor 内可选启用），此处做快速估算
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿" or "぀" <= ch <= "ヿ")
    other = len(text) - cjk
    return int(cjk * 0.9 + other / 3.5) + 1
