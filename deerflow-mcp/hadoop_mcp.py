"""DeerFlow MCP 服务器：Hadoop 集群监控工具（只读）。

封装 Hadoop 3.3.6 的三个 REST 入口，让对话式 Agent 可以查看
HDFS 存储、DataNode 状态、YARN 资源调度、队列与作业情况：

    1. NameNode JMX     —— HDFS 容量/块/DataNode 存活（Web UI 端口）
    2. WebHDFS REST     —— 目录浏览、目录大小统计（LISTSTATUS/GETCONTENTSUMMARY）
    3. ResourceManager  —— YARN 集群指标、节点、队列（capacityScheduler）、应用列表

设计为纯只读：不提供任何 HDFS 写/删操作（写数据走 SeaTunnel 等专业通道）。

环境变量：
    HADOOP_NN_URL   NameNode Web/REST 地址（默认 http://10.131.102.144:30870）
    YARN_RM_URL     ResourceManager REST 地址（默认 http://10.131.102.144:30888）
    PORT            HTTP 监听端口（默认 9112）
"""

import json
import os
from datetime import datetime

import httpx
from mcp.server.fastmcp import FastMCP

NN_URL = os.environ.get("HADOOP_NN_URL", "http://10.131.102.144:30870").rstrip("/")
RM_URL = os.environ.get("YARN_RM_URL", "http://10.131.102.144:30888").rstrip("/")
PORT = int(os.environ.get("PORT", "9112"))

mcp = FastMCP("hadoop-mcp", host="0.0.0.0", port=PORT)

_client = httpx.Client(timeout=30.0)

# YARN 应用状态合法值（用于 yarn_apps 的 states 参数校验）
YARN_APP_STATES = {
    "NEW", "NEW_SAVING", "SUBMITTED", "ACCEPTED", "RUNNING",
    "FINISHED", "FAILED", "KILLED",
}


def _get(url: str) -> dict:
    """GET 一个 JSON 接口，失败时抛出带状态码的异常信息（由调用方兜底）。"""
    resp = _client.get(url)
    resp.raise_for_status()
    return resp.json()


def _safe(fn) -> str:
    """统一兜底：正常返回 JSON 字符串，异常返回 {"error": ...}。"""
    try:
        return json.dumps(fn(), ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


def _gb(nbytes) -> str:
    """字节数转人类可读的 GB/MB 字符串。"""
    if nbytes is None:
        return "?"
    gb = nbytes / 1024**3
    return f"{gb:.2f} GB" if gb >= 1 else f"{nbytes / 1024**2:.2f} MB"


def _hdfs_summary() -> dict:
    """HDFS 核心指标：容量/DataNode/块/文件（来自 NameNode JMX）。"""
    fs = _get(f"{NN_URL}/jmx?qry=Hadoop:service=NameNode,name=FSNamesystem")["beans"][0]
    info = _get(f"{NN_URL}/jmx?qry=Hadoop:service=NameNode,name=NameNodeInfo")["beans"][0]
    total, used = fs.get("CapacityTotal", 0), fs.get("CapacityUsed", 0)
    remaining = fs.get("CapacityRemaining", 0)
    return {
        "version": info.get("Version"),
        "state": info.get("State", "?"),  # NameNode 角色（active/standby）
        "capacity": {
            "total": _gb(total),
            "used": _gb(used),
            "remaining": _gb(remaining),
            "used_pct": f"{(used / total * 100):.2f}%" if total else "?",
        },
        "datanodes": {
            "live": fs.get("NumLiveDataNodes"),
            "dead": fs.get("NumDeadDataNodes"),
            "decommissioning": fs.get("NumDecommissioningDataNodes"),
        },
        "blocks": {
            "total": fs.get("BlocksTotal"),
            "missing": fs.get("MissingBlocks"),
            "under_replicated": fs.get("UnderReplicatedBlocks"),
            "corrupt": fs.get("CorruptBlocks"),
        },
        "files_total": fs.get("FilesTotal"),
        "last_checkpoint": info.get("LastCheckpointTime"),
    }


def _yarn_metrics() -> dict:
    """YARN 集群资源指标（内存/vCore/应用计数/活跃节点）。"""
    m = _get(f"{RM_URL}/ws/v1/cluster/metrics")["clusterMetrics"]
    total_mb = m.get("totalMB", 0)
    return {
        "memory_mb": {
            "total": total_mb,
            "allocated": m.get("allocatedMB"),
            "available": m.get("availableMB"),
            "used_pct": f"{m.get('allocatedMB', 0) / total_mb * 100:.1f}%" if total_mb else "?",
        },
        "vcores": {
            "total": m.get("totalVirtualCores"),
            "allocated": m.get("allocatedVirtualCores"),
            "available": m.get("availableVirtualCores"),
        },
        "nodes": {
            "active": m.get("activeNodes"),
            "lost": m.get("lostNodes"),
            "unhealthy": m.get("unhealthyNodes"),
        },
        "apps": {
            "submitted": m.get("appsSubmitted"),
            "running": m.get("appsRunning"),
            "pending": m.get("appsPending"),
            "completed": m.get("appsCompleted"),
            "failed": m.get("appsFailed"),
            "killed": m.get("appsKilled"),
        },
    }


@mcp.tool()
def hadoop_overview() -> str:
    """一次性获取 Hadoop 集群全貌：HDFS 存储 + YARN 资源 + 队列摘要。

    适合作为对话的第一个入口，先看整体健康度再深入某个方面。
    """
    def run():
        out = {"hdfs": _hdfs_summary(), "yarn": _yarn_metrics()}
        try:
            q = _get(f"{RM_URL}/ws/v1/cluster/scheduler")["scheduler"]["schedulerInfo"]
            out["yarn"]["queues"] = [x["queueName"] for x in q.get("queues", {}).get("queue", [])]
        except Exception:
            pass  # 队列信息失败不阻塞整体概览
        return out
    return _safe(run)


@mcp.tool()
def hdfs_status() -> str:
    """查看 HDFS 存储详情：容量/已用/剩余、DataNode 存活、块健康度、文件总数。

    关注点：used_pct 持续上涨说明存储吃紧；missing/corrupt 块应始终为 0。
    """
    return _safe(_hdfs_summary)


@mcp.tool()
def hdfs_list_dir(path: str = "/") -> str:
    """浏览 HDFS 目录（列子目录/文件：名称、大小、属主、权限、修改时间）。

    Args:
        path: HDFS 绝对路径（默认根目录 /，如 /user/hive/warehouse）
    """
    if not path.startswith("/"):
        path = "/" + path
    def run():
        d = _get(f"{NN_URL}/webhdfs/v1{path}?op=LISTSTATUS")
        items = d.get("FileStatuses", {}).get("FileStatus", [])
        rows = [{
            "type": "DIR" if i.get("type") == "DIRECTORY" else "FILE",
            "name": i.get("pathSuffix"),
            "size": _gb(i.get("length", 0)) if i.get("type") != "DIRECTORY" else f"{i.get('childrenNum', 0)} items",
            "owner": i.get("owner"),
            "permission": i.get("permission"),
            "modified": datetime.fromtimestamp(i.get("modificationTime", 0) / 1000).strftime("%Y-%m-%d %H:%M"),
        } for i in items]
        return {"path": path, "count": len(rows), "entries": rows}
    return _safe(run)


@mcp.tool()
def hdfs_dir_size(path: str) -> str:
    """统计一个 HDFS 目录的总大小、文件数、目录数（GETCONTENTSUMMARY）。

    适合回答"某张 Hive 表/某个目录占了多少存储"。
    注意：HDFS 配额与回收站不在此统计内。

    Args:
        path: HDFS 绝对路径（如 /user/hive/warehouse/testdb.db）
    """
    if not path.startswith("/"):
        path = "/" + path
    def run():
        d = _get(f"{NN_URL}/webhdfs/v1{path}?op=GETCONTENTSUMMARY")["ContentSummary"]
        return {
            "path": path,
            "length": _gb(d.get("length")),
            "files": d.get("fileCount"),
            "dirs": d.get("directoryCount"),
            "quota": d.get("quota"),
        }
    return _safe(run)


@mcp.tool()
def yarn_cluster() -> str:
    """查看 YARN 集群状态：RM 状态、资源池（内存/vCore）、应用计数、节点健康。"""
    def run():
        info = _get(f"{RM_URL}/ws/v1/cluster/info")["clusterInfo"]
        return {"cluster": info, "metrics": _yarn_metrics()}
    return _safe(run)


@mcp.tool()
def yarn_nodes() -> str:
    """列出 YARN 的 NodeManager 节点：内存/vCore 分配、运行中的应用数、健康状态。"""
    def run():
        d = _get(f"{RM_URL}/ws/v1/cluster/nodes")
        nodes = d.get("nodes", {}).get("node", [])
        return [{
            "node": n.get("nodeHostName"),
            "state": n.get("state"),
            "healthy": n.get("healthReport", "") == "healthy" or n.get("healthy"),
            "memory": f"{n.get('usedMemoryMB', 0)}/{n.get('memoryCapabilityMB', 0)} MB",
            "vcores": f"{n.get('usedVirtualCores', 0)}/{n.get('availableVirtualCores', 0) + n.get('usedVirtualCores', 0)}",
            "running_apps": n.get("numRunningApps"),
        } for n in nodes]
    return _safe(run)


@mcp.tool()
def yarn_queues() -> str:
    """查看 YARN 队列（CapacityScheduler）：容量、已用、状态、应用数、资源占用。

    适合回答"队列配置如何、哪个队列在排队"。
    """
    def run():
        s = _get(f"{RM_URL}/ws/v1/cluster/scheduler")["scheduler"]["schedulerInfo"]
        def fmt(q):
            return {
                "queue": q.get("queueName"),
                "capacity_pct": q.get("capacity"),
                "used_pct": q.get("usedCapacity"),
                "max_capacity_pct": q.get("maxCapacity"),
                "state": q.get("state"),
                "apps": q.get("numApplications"),
                "resources_used": q.get("resourcesUsed", {}),
                # 子队列递归（ CapacityScheduler 队列可嵌套）
                "children": [fmt(c) for c in q.get("queues", {}).get("queue", [])] if q.get("queues") else [],
            }
        return fmt(s)
    return _safe(run)


@mcp.tool()
def yarn_apps(states: str = "RUNNING", app_type: str = "") -> str:
    """列出 YARN 中的应用（含 MapReduce/Spark/Flink 等提交到 YARN 的作业）。

    查 MapReduce 运行情况：app_type 传 "MAPREDUCE"；
    查所有运行中的：states 保持默认 RUNNING。

    Args:
        states: 逗号分隔的状态过滤（默认 RUNNING），
                可选 NEW/NEW_SAVING/SUBMITTED/ACCEPTED/RUNNING/FINISHED/FAILED/KILLED，
                如 "FINISHED,FAILED"
        app_type: 可选应用类型过滤（MAPREDUCE/SPARK/FLINK 等，空为全部）
    """
    # 校验状态值，防注入
    wanted = [s.strip().upper() for s in states.split(",") if s.strip()]
    bad = [s for s in wanted if s not in YARN_APP_STATES]
    if bad:
        return f"ERROR: 非法状态值 {bad}，可选：{sorted(YARN_APP_STATES)}"
    def run():
        url = f"{RM_URL}/ws/v1/cluster/apps?states={','.join(wanted)}"
        if app_type:
            url += f"&applicationTypes={app_type.strip().upper()}"
        d = _get(url)
        apps = d.get("apps") or {}  # 无应用时 YARN 返回 "apps": {} 而非列表
        rows = [{
            "id": a.get("id"),
            "name": a.get("name"),
            "type": a.get("applicationType"),
            "queue": a.get("queue"),
            "state": a.get("state"),
            "finalStatus": a.get("finalStatus"),
            "progress": f"{a.get('progress', 0)}%",
            "memoryMB": a.get("allocatedMB"),
            "vcores": a.get("allocatedVCores"),
            "started": datetime.fromtimestamp(a.get("startedTime", 0) / 1000).strftime("%m-%d %H:%M") if a.get("startedTime") else "?",
            "runtime_sec": round((a.get("finishedTime", 0) or _now_ms()) - a.get("startedTime", 0)) / 1000 if a.get("startedTime") else None,
        } for a in apps.get("app", [])]
        return {"states": wanted, "type": app_type or "ALL", "count": len(rows), "apps": rows}
    return _safe(run)


def _now_ms() -> int:
    """当前时间戳（毫秒），用于计算未结束应用的运行时长。"""
    return int(datetime.now().timestamp() * 1000)


@mcp.tool()
def yarn_queue_apps(queue: str, states: str = "RUNNING") -> str:
    """查看某个 YARN 队列里的应用（排队/运行/完成的）。

    适合回答"default 队列现在有多少任务在跑、有没有排队"。

    Args:
        queue: 队列名（如 default，可用名称从 yarn_queues 获取）
        states: 状态过滤（默认 RUNNING，可选值同 yarn_apps）
    """
    if not queue or not queue.strip():
        return "ERROR: queue 不能为空。"
    wanted = [s.strip().upper() for s in states.split(",") if s.strip()]
    bad = [s for s in wanted if s not in YARN_APP_STATES]
    if bad:
        return f"ERROR: 非法状态值 {bad}，可选：{sorted(YARN_APP_STATES)}"
    def run():
        url = f"{RM_URL}/ws/v1/cluster/apps?states={','.join(wanted)}&queue={queue.strip()}"
        d = _get(url)
        apps = d.get("apps") or {}
        rows = [{
            "id": a.get("id"), "name": a.get("name"), "type": a.get("applicationType"),
            "state": a.get("state"), "progress": f"{a.get('progress', 0)}%",
            "memoryMB": a.get("allocatedMB"),
        } for a in apps.get("app", [])]
        return {"queue": queue.strip(), "states": wanted, "count": len(rows), "apps": rows}
    return _safe(run)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
