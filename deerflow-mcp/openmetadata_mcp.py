"""DeerFlow MCP 服务器：OpenMetadata 数据治理工具。

封装 OpenMetadata REST API（v1），让对话式 Agent 可以检索元数据、
查看表/列详情、追溯数据血缘。

环境变量：
    OM_URL       服务地址（默认 http://10.131.102.144:8585）
    OM_USERNAME  登录邮箱（默认 admin@open-metadata.org）
    OM_PASSWORD  登录密码（默认 admin）
    PORT         HTTP 监听端口（默认 9105）
"""

import json
import os
import threading

import httpx
from mcp.server.fastmcp import FastMCP

OM_URL = os.environ.get("OM_URL", "http://10.131.102.144:8585").rstrip("/")
OM_USERNAME = os.environ.get("OM_USERNAME", "admin@open-metadata.org")
OM_PASSWORD = os.environ.get("OM_PASSWORD", "admin")
PORT = int(os.environ.get("PORT", "9105"))

mcp = FastMCP("openmetadata-mcp", host="0.0.0.0", port=PORT)

_client = httpx.Client(timeout=60.0)
_token: str | None = None
_lock = threading.Lock()


def _login() -> str:
    """登录一次并缓存 JWT token（线程安全）。"""
    global _token
    with _lock:
        if _token:
            return _token
        import base64

        # OpenMetadata 1.13 登录接口要求密码先做 base64 编码
        resp = _client.post(
            f"{OM_URL}/api/v1/users/login",
            json={
                "email": OM_USERNAME,
                "password": base64.b64encode(OM_PASSWORD.encode()).decode(),
            },
        )
        resp.raise_for_status()
        _token = resp.json().get("accessToken")
        if not _token:
            raise RuntimeError("OpenMetadata 登录未返回 accessToken")
        return _token


def _api(path: str, params: dict | None = None) -> str:
    """带鉴权地 GET 一个 OM API 路径；遇 401 时刷新 token 重试一次。"""
    for attempt in range(2):
        headers = {"Authorization": f"Bearer {_login()}"}
        resp = _client.get(f"{OM_URL}{path}", headers=headers, params=params)
        if resp.status_code == 401 and attempt == 0:
            global _token
            with _lock:
                _token = None
            continue
        try:
            return json.dumps(resp.json(), ensure_ascii=False)
        except Exception:
            return f"HTTP {resp.status_code}: {resp.text[:400]}"


@mcp.tool()
def search_metadata(query: str, entity_type: str = "table", size: int = 10) -> str:
    """对 OpenMetadata 做全文检索（表、看板、主题、流水线等）。

    Args:
        query: 自由文本检索词（表名、列名、描述、标签）
        entity_type: table|database|dashboard|topic|pipeline|glossary（默认 table）
        size: 最多返回条数
    """
    # 实体类型 -> 检索索引名的映射（OpenMetadata 1.13 实际索引名）
    index_map = {
        "table": "table_search_index",
        "dashboard": "dashboard_search_index",
        "topic": "topic_search_index",
        "pipeline": "pipeline_search_index",
        "glossary": "glossary_term_index",
    }
    return _api(
        "/api/v1/search/query",
        params={
            "q": query,
            "index": index_map.get(entity_type, "table_search_index"),
            "size": size,
        },
    )


@mcp.tool()
def get_table_details(fqn: str) -> str:
    """按全限定名（FQN）获取表的完整详情。

    返回列（名称/类型/描述/标签）、表画像统计、所有者等信息。
    FQN 格式：<服务名>.<数据库>.<模式>.<表名>

    Args:
        fqn: 表的全限定名，例如 mysql_svc.his_demo.main.person
    """
    from urllib.parse import quote

    return _api(
        f"/api/v1/tables/name/{quote(fqn, safe='')}",
        params={
            "fields": "columns,tags,owner,profile,tableConstraints,dataModel"
        },
    )


@mcp.tool()
def get_lineage(fqn: str, entity_type: str = "table", depth: int = 1) -> str:
    """获取实体的上下游血缘（数据从哪里来、流向哪里）。

    Args:
        fqn: 实体的全限定名
        entity_type: table|dashboard|pipeline（默认 table）
        depth: 血缘遍历深度，默认 1
    """
    from urllib.parse import quote

    return _api(
        f"/api/v1/lineage/{entity_type}/{quote(fqn, safe='')}",
        params={"upstreamDepth": depth, "downstreamDepth": depth},
    )


@mcp.tool()
def list_database_services() -> str:
    """列出已注册的数据服务（MySQL/PG/Doris/Trino 等）及连接信息。"""
    # 注意：该接口不支持 fields 参数（owner 等字段会报错）
    return _api("/api/v1/services/databaseServices", params={"limit": 50})


@mcp.tool()
def list_tables(service_name: str, limit: int = 50) -> str:
    """列出某个数据库服务下的表。

    Args:
        service_name: 服务名（从 list_database_services 获取）
        limit: 最多返回表数
    """
    return _api(
        "/api/v1/tables",
        params={
            "service": service_name,
            "fields": "columns",
            "limit": limit,
        },
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
