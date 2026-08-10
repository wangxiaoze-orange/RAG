"""解析器独立测试脚本 —— 不依赖后端服务，直接验证各格式解析结果
用法：cd backend  →  python test_parser_standalone.py
"""
import io
import os
import sys
import tempfile

# 确保能 import 到 src 下的模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from ingestion.parser_v2 import _parse_html, _parse_excel, _parse_csv, try_parse_v2

PASS = "[OK]"
FAIL = "[FAIL]"
results = []


def report(name: str, ok: bool, detail: str = ""):
    tag = PASS if ok else FAIL
    msg = f"  {tag} {name}"
    if detail and not ok:
        msg += f"  —— {detail}"
    print(msg)
    results.append(ok)


# ──────────────────────────────────────────────
# 1. HTML 解析
# ──────────────────────────────────────────────
print("\n═══ HTML 解析 ═══")

html_str = """<!DOCTYPE html>
<html>
<head><title>Test</title><style>body{color:red}</style></head>
<body>
<h1>标题一</h1>
<p>这是第一段正文。</p>
<script>alert('xss')</script>
<p>这是第二段正文。</p>
<footer>页脚内容</footer>
</body>
</html>"""
html_data = html_str.encode("utf-8")

text = _parse_html(html_data)
report("HTML 提取正文", "标题一" in text and "第一段" in text and "第二段" in text, text[:100])
report("HTML 移除 script", "alert" not in text, text)
report("HTML 移除 style", "color:red" not in text, text)
report("HTML 移除 footer", "页脚" not in text, text)

# 通过 try_parse_v2 委托调用
text2, parser = try_parse_v2("html", html_data)
report("try_parse_v2 html", parser == "html" and "标题一" in text2, f"parser={parser}")


# ──────────────────────────────────────────────
# 2. Excel 解析
# ──────────────────────────────────────────────
print("\n═══ Excel 解析 ═══")

import openpyxl
wb = openpyxl.Workbook()
ws1 = wb.active
ws1.title = "Sheet1"
ws1.append(["姓名", "年龄", "城市"])
ws1.append(["张三", 28, "北京"])
ws1.append(["李四", 35, "上海"])
ws1.append([None, None, None])  # 全空行，应被跳过
ws1.append(["王五", 22, "广州"])

ws2 = wb.create_sheet("数据表2")
ws2.append(["A", "B"])
ws2.append([1, 2])

buf = io.BytesIO()
wb.save(buf)
excel_data = buf.getvalue()
wb.close()

text = _parse_excel(excel_data)
report("Excel 表头", "姓名" in text and "年龄" in text, text[:100])
report("Excel 数据行", "张三" in text and "28" in text and "北京" in text, text)
report("Excel 多 sheet", "数据表2" in text and "A" in text, text)
report("Excel 管道分隔", "| " in text, text)

text2, parser = try_parse_v2("xlsx", excel_data)
report("try_parse_v2 xlsx", parser == "excel" and "张三" in text2, f"parser={parser}")


# ──────────────────────────────────────────────
# 3. CSV 解析
# ──────────────────────────────────────────────
print("\n═══ CSV 解析 ═══")

csv_data = "姓名,年龄,城市\n张三,28,北京\n李四,35,上海\n,,\n王五,22,广州\n".encode("utf-8")

text = _parse_csv(csv_data)
report("CSV 表头", "姓名" in text, text[:80])
report("CSV 数据行", "张三" in text and "28" in text, text)
report("CSV 跳过空行", text.count("\n") == 3, f"行数={text.count(chr(10))+1}")  # 4行数据 = 3个换行
report("CSV 管道分隔", "| " in text, text)

text2, parser = try_parse_v2("csv", csv_data)
report("try_parse_v2 csv", parser == "csv" and "张三" in text2, f"parser={parser}")

# CSV GBK 编码
csv_gbk = "姓名,城市\n张三,北京\n李四,上海\n".encode("gbk")
text3, parser3 = try_parse_v2("csv", csv_gbk)
report("CSV GBK 编码", parser3 == "csv" and "张三" in text3, f"parser={parser3}")


# ──────────────────────────────────────────────
# 4. try_parse_v2 不支持的格式
# ──────────────────────────────────────────────
print("\n═══ try_parse_v2 不支持格式 ═══")

text, parser = try_parse_v2("png", b"\x89PNG\r\n")
report("PNG 返回 None", text is None and parser == "", f"text={text}, parser={parser}")


# ──────────────────────────────────────────────
# 汇总
# ──────────────────────────────────────────────
print("\n" + "═" * 40)
total = len(results)
passed = sum(results)
failed = total - passed
if failed == 0:
    print(f"  ALL PASSED {passed}/{total}")
else:
    print(f"  FAILED {failed}/{total}")
    sys.exit(1)
