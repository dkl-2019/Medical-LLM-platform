"""DeerFlow MCP 共享工具模块：MySQL/PostgreSQL/Trino/Hive MCP 服务器的公共函数。"""

import datetime
import decimal
import json
import re
import uuid

# 查询结果最大返回行数
MAX_ROWS = 200

# read_query 允许的语句类型：仅纯读取操作
_READONLY_RE = re.compile(r"^\s*(select|with|show|explain|describe|desc)\b", re.IGNORECASE)

# 用于拦截"分号后还有内容"的多语句写法
FORBIDDEN_IN_READ = re.compile(r";\s*\S")


def is_readonly_sql(sql: str) -> bool:
    """判断 *sql* 是否为单条只读语句。"""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return False
    if ";" in stripped:  # 不允许多条语句
        return False
    return bool(_READONLY_RE.match(stripped))


def json_default(value):
    """JSON 序列化数据库特有类型（时间、 Decimal、字节、UUID 等）。"""
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def rows_to_json(rows, max_rows: int = MAX_ROWS) -> str:
    """把查询结果（字典列表）转成紧凑的 JSON 字符串，超限自动截断。"""
    truncated = len(rows) > max_rows
    payload = {
        "row_count": len(rows),
        "rows": rows[:max_rows],
    }
    if truncated:
        payload["notice"] = f"结果已截断：共 {len(rows)} 行，仅返回前 {max_rows} 行"
    return json.dumps(payload, default=json_default, ensure_ascii=False)
