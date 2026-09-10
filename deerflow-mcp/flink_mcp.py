"""DeerFlow MCP 服务器：Apache Flink Session Cluster 工具。

封装 Flink 1.20 Session Cluster 的 REST API（v1），
让对话式 Agent 可以查看集群状态、上传/提交作业、查询/终止作业。

环境变量：
    FLINK_REST_URL  JobManager REST 根地址（默认 http://10.131.102.144:32181）
    PORT            HTTP 监听端口（默认 9111）
"""

import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("FLINK_REST_URL", "http://10.131.102.144:32181").rstrip("/")
PORT = int(os.environ.get("PORT", "9111"))

mcp = FastMCP("flink-mcp", host="0.0.0.0", port=PORT)

_client = httpx.Client(timeout=60.0)


def _fmt(response: httpx.Response) -> str:
    """把 HTTP 响应格式化为字符串：优先 JSON，失败则退回状态码+文本。"""
    try:
        return json.dumps(response.json(), ensure_ascii=False)
    except Exception:
        return f"HTTP {response.status_code}: {response.text[:500]}"


@mcp.tool()
def flink_overview() -> str:
    """一次性获取 Flink 集群全貌：版本、TaskManager 数、可用槽、运行/已完成作业数。

    适合作为对话的第一个入口，先了解集群情况再决定提交什么。
    """
    summary = _fmt(_client.get(f"{BASE_URL}/overview"))
    jobs = _fmt(_client.get(f"{BASE_URL}/jobs/overview"))
    return json.dumps(
        {"cluster": json.loads(summary), "jobs": json.loads(jobs)},
        ensure_ascii=False,
    )


@mcp.tool()
def list_jobs(filter: str = "all") -> str:
    """列出 Flink 作业。

    Args:
        filter: all | running | completed（默认 all）。Flink 状态枚举：
                RUNNING / FINISHED / CANCELED / FAILED / SCHEDULED / DEPLOYING / FAILING
    """
    data = _client.get(f"{BASE_URL}/jobs/overview").json()
    jobs = data.get("jobs", []) or []
    if filter != "all":
        want = filter.upper()
        jobs = [j for j in jobs if j.get("state") == want]
    rows = [
        {
            "jid": j.get("jid"),
            "name": j.get("name"),
            "state": j.get("state"),
            "start-time": j.get("start-time"),
            "duration": j.get("duration"),
        }
        for j in jobs
    ]
    return json.dumps({"count": len(rows), "jobs": rows}, ensure_ascii=False)


@mcp.tool()
def get_job(job_id: str) -> str:
    """查询单个 Flink 作业的详细信息：状态、运行时间、TaskManager、计划。

    Args:
        job_id: 作业 ID（jid，来自 list_jobs 的 jid 字段）
    """
    info = _fmt(_client.get(f"{BASE_URL}/jobs/{job_id}"))
    try:
        plan = _client.get(f"{BASE_URL}/jobs/{job_id}/plan").json()
    except Exception:
        plan = {"note": "plan 不可用"}
    return json.dumps(
        {"info": json.loads(info), "plan": plan}, ensure_ascii=False
    )


@mcp.tool()
def list_uploaded_jars() -> str:
    """列出已上传到 JobManager 的 jar 列表（含 jar ID）。提交作业时用 jar ID 启动。"""
    return _fmt(_client.get(f"{BASE_URL}/jars"))


@mcp.tool()
def upload_jar(jar_path: str) -> str:
    """上传一个 jar 到 JobManager（multipart/form-data）。

    提交作业前先用此工具上传 jar，再用 run_uploaded_jar 启动。
    返回的 jarId 传给 run_uploaded_jar 的 jar_id 参数。

    Args:
        jar_path: MCP 容器本地可访问的 jar 绝对路径。
                  145 上的 /data/deerflow-mcp 目录在容器里是 /app/...
                  如果要把宿主机 jar 上传给 flink,需先把 jar 拷贝到容器里再调用。
    """
    if not jar_path or not jar_path.startswith("/"):
        return "ERROR: jar_path 必须是容器内绝对路径（以 / 开头）。"
    try:
        with open(jar_path, "rb") as f:
            files = {"jarfile": (os.path.basename(jar_path), f, "application/java-archive")}
            resp = _client.post(f"{BASE_URL}/jars/upload", files=files)
    except FileNotFoundError:
        return f"ERROR: 文件不存在：{jar_path}"
    return _fmt(resp)


@mcp.tool()
def run_uploaded_jar(jar_id: str, entry_class: str, program_args: str = "") -> str:
    """启动一个已上传的 jar 作业（jarId 来自 upload_jar / list_uploaded_jars）。

    Args:
        jar_id:       已上传 jar 的 ID
        entry_class:  含 main 方法的 FQCN（entryClass）
        program_args: 传给 main 的参数（空格分隔，可为空）
    """
    if not jar_id or not entry_class:
        return "ERROR: jar_id 与 entry_class 都不能为空。"
    args = program_args.split() if program_args else []
    params = [
        ("entryClass", entry_class),
        ("parallelism", "1"),
    ]
    for i, a in enumerate(args):
        params.append((f"programArgs[{i}]", a))
    resp = _client.post(f"{BASE_URL}/jars/{jar_id}/run", params=params)
    return _fmt(resp)


@mcp.tool()
def cancel_job(job_id: str) -> str:
    """取消一个正在运行的 Flink 作业（保留状态）。

    安全要求：取消非本次会话启动的作业前，必须先与用户确认。

    Args:
        job_id: 作业 ID（jid）
    """
    if not job_id:
        return "ERROR: job_id 不能为空。"
    resp = _client.patch(f"{BASE_URL}/jobs/{job_id}", params={"mode": "cancel"})
    return _fmt(resp)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
