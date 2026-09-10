"""DeerFlow MCP 服务器：Spark Standalone Cluster 工具。

封装 Spark Standalone Master 的 Cluster REST API（v1），
让对话式 Agent 可以查看集群状态、上传/提交作业、查询/终止应用。

环境变量：
    SPARK_MASTER_URL  Master REST 根地址（默认 http://10.131.102.144:32080）
    PORT              HTTP 监听端口（默认 9110）
"""

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("SPARK_MASTER_URL", "http://10.131.102.144:32080").rstrip("/")
PORT = int(os.environ.get("PORT", "9110"))

mcp = FastMCP("spark-mcp", host="0.0.0.0", port=PORT)

_client = httpx.Client(timeout=60.0)


def _fmt(response: httpx.Response) -> str:
    """把 HTTP 响应格式化为字符串：优先 JSON，失败则退回状态码+文本。"""
    try:
        return json.dumps(response.json(), ensure_ascii=False)
    except Exception:
        return f"HTTP {response.status_code}: {response.text[:500]}"


@mcp.tool()
def spark_overview() -> str:
    """一次性获取 Spark Standalone 集群全貌：Master 状态、Worker 数、应用数。

    适合作为对话的第一个入口，先了解集群情况再决定提交什么。
    """
    return _fmt(_client.get(f"{BASE_URL}/json/"))


@mcp.tool()
def list_workers() -> str:
    """列出所有 Worker（id、IP、可用内存/核数、运行时长）。"""
    data = _client.get(f"{BASE_URL}/json/").json()
    return json.dumps(data.get("workers", []), ensure_ascii=False)


@mcp.tool()
def list_apps(filter: str = "all") -> str:
    """列出 Spark 应用（driver）。

    Args:
        filter: all | running | completed（默认 all）
    """
    data = _client.get(f"{BASE_URL}/json/").json()
    active = data.get("activeapps", []) or []
    completed = data.get("completedapps", []) or []
    if filter == "running":
        apps = active
    elif filter == "completed":
        apps = completed
    else:
        apps = active + completed
    # 精简每条记录：name/id/state/submitTime/duration
    rows = [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "state": a.get("state"),
            "submitTime": a.get("submitTime"),
            "duration": a.get("duration"),
        }
        for a in apps
    ]
    return json.dumps({"count": len(rows), "apps": rows}, ensure_ascii=False)


@mcp.tool()
def get_app(app_id: str) -> str:
    """查询单个应用的详情：状态、Spark UI 地址、提交参数、运行时间。

    Args:
        app_id: 应用 ID（来自 list_apps 的 id 字段）
    """
    return _fmt(_client.get(f"{BASE_URL}/json/app/{app_id}"))


@mcp.tool()
def submit_app(jar_path: str, main_class: str, app_args: str = "") -> str:
    """提交 Spark 应用到 Standalone 集群。

    作业通过 Master REST 提交（cluster mode），返回 driverId。
    应用启动后用 list_apps/get_app 跟踪状态。

    Args:
        jar_path:     集群可访问的 jar 路径（http/https/HDFS/Spark 兼容 URL，
                      或在 Spark Master NodePort 节点上的绝对路径）
        main_class:   包含 main 方法的 FQCN
        app_args:     传给 main 方法的参数，空格分隔（可为空）
    """
    if not jar_path or not main_class:
        return "ERROR: jar_path 与 main_class 都不能为空。"
    args = app_args.split() if app_args else []
    files = {
        "appResource": (None, jar_path),
        "mainClass": (None, main_class),
    }
    for i, a in enumerate(args):
        files[f"appArgs[{i}]"] = (None, a)
    resp = _client.post(f"{BASE_URL}/json/submit-app/", files=files)
    return _fmt(resp)


@mcp.tool()
def kill_app(app_id: str, driver_id: str = "") -> str:
    """终止一个正在运行的 Spark 应用（standalone mode）。

    安全要求：终止非本次会话启动的应用前，必须先与用户确认。

    Args:
        app_id:    应用 ID
        driver_id: driver ID（来自 get_app/app-* 的 driverId 字段；空时自动查）
    """
    if not app_id:
        return "ERROR: app_id 不能为空。"
    if not driver_id:
        info = _client.get(f"{BASE_URL}/json/app/{app_id}").json()
        driver_id = info.get("driverId", "") or info.get("id", "")
    if not driver_id:
        return "ERROR: 找不到 driver_id，请手动传入。"
    resp = _client.post(f"{BASE_URL}/json/kill/{app_id}/{driver_id}")
    return _fmt(resp)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
