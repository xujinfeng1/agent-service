"""内置工具集"""
import json
import os
from datetime import datetime
from src.tools import registry, ToolParameter

# ========== 系统工具 ==========

@registry.register(
    name="get_current_time",
    description="获取当前日期和时间",
    parameters=[
        ToolParameter(name="timezone", type="string",
                      description="时区，如 Asia/Shanghai，默认 Asia/Shanghai",
                      required=False),
    ],
)
def get_current_time(timezone: str = "Asia/Shanghai") -> str:
    now = datetime.now()
    return json.dumps({
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp": int(now.timestamp()),
        "timezone": timezone,
    }, ensure_ascii=False)


@registry.register(
    name="calculate",
    description="执行数学计算，支持基本运算和函数",
    parameters=[
        ToolParameter(name="expression", type="string",
                      description="数学表达式，如 '2+3*4' 或 'sqrt(16)+10'",
                      required=True),
    ],
)
def calculate(expression: str) -> str:
    # 安全的数学计算
    import math
    allowed = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "pow": pow,
        "sqrt": math.sqrt, "log": math.log, "log10": math.log10,
        "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "pi": math.pi, "e": math.e,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed)
        return json.dumps({"expression": expression, "result": result}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ========== 文件操作工具 ==========

@registry.register(
    name="read_file",
    description="读取本地文件内容",
    parameters=[
        ToolParameter(name="path", type="string",
                      description="文件绝对路径", required=True),
        ToolParameter(name="lines", type="number",
                      description="读取行数，不传则读取全部", required=False),
    ],
)
def read_file(path: str, lines: int = None) -> str:
    if not os.path.exists(path):
        return json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False)
    try:
        with open(path, "r", encoding="utf-8") as f:
            if lines:
                content = "".join(f.readline() for _ in range(lines))
            else:
                content = f.read()
        return json.dumps({"path": path, "content": content[:5000]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@registry.register(
    name="list_directory",
    description="列出目录下的文件和子目录",
    parameters=[
        ToolParameter(name="path", type="string",
                      description="目录路径", required=True),
    ],
)
def list_directory(path: str) -> str:
    if not os.path.isdir(path):
        return json.dumps({"error": f"不是有效目录: {path}"}, ensure_ascii=False)
    try:
        items = []
        for name in os.listdir(path):
            full = os.path.join(path, name)
            items.append({
                "name": name,
                "type": "dir" if os.path.isdir(full) else "file",
                "size": os.path.getsize(full) if os.path.isfile(full) else None,
            })
        return json.dumps({"path": path, "items": items[:50]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


@registry.register(
    name="write_file",
    description="写入内容到文件（覆盖写入）",
    parameters=[
        ToolParameter(name="path", type="string",
                      description="文件路径", required=True),
        ToolParameter(name="content", type="string",
                      description="要写入的内容", required=True),
    ],
)
def write_file(path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return json.dumps({"success": True, "path": path,
                           "size": len(content)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ========== Web 工具 ==========

@registry.register(
    name="web_fetch",
    description="抓取网页内容（仅文本）",
    parameters=[
        ToolParameter(name="url", type="string",
                      description="要抓取的网页 URL", required=True),
    ],
)
async def web_fetch(url: str) -> str:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            resp.raise_for_status()
        # 简单提取文本（去掉 HTML 标签）
        import re
        text = re.sub(r"<[^>]+>", " ", resp.text)
        text = re.sub(r"\s+", " ", text).strip()
        return json.dumps({"url": url, "status": resp.status_code,
                           "content": text[:3000]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
