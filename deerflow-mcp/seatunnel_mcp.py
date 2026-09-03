"""DeerFlow MCP 服务器：Apache SeaTunnel（Zeta 引擎）作业管理工具。

把 SeaTunnel 2.3.x REST API（v1）封装成 MCP 工具，让对话式 Agent
可以提交数据同步作业、查询作业状态、停止作业。

环境变量：
    SEATUNNEL_URL  Zeta REST 服务地址（默认 http://10.131.102.145:8080）
    PORT           HTTP 监听端口（默认 9103）
    MYSQL_PASSWORD / PG_PASSWORD  用于自动注入的真实密码（见 _inject_credentials）
"""

import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("SEATUNNEL_URL", "http://10.131.102.145:8080").rstrip("/")
PORT = int(os.environ.get("PORT", "9103"))
TIMEOUT = 60.0

mcp = FastMCP("seatunnel-mcp", host="0.0.0.0", port=PORT)

_client = httpx.Client(timeout=TIMEOUT)


# 占位符集合：作业配置中出现这些"假密码"时，由服务端自动替换为真实密码
PLACEHOLDERS = {"...", "***", "******", "", "$MYSQL_PASSWORD", "$PG_PASSWORD"}

MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "")


def _inject_credentials(node):
    """递归地把占位符密码替换为真实凭据。

    通过同节点兄弟字段 "url" 判断方言（mysql / postgresql），
    因此同一条规则同时覆盖 MySQL source 和 PostgreSQL sink。
    """
    if isinstance(node, dict):
        url = str(node.get("url", ""))
        is_mysql = "mysql" in url
        is_pg = "postgresql" in url
        for key, value in node.items():
            if (
                key.lower() == "password"
                and isinstance(value, str)
                and value.strip() in PLACEHOLDERS
            ):
                if is_mysql and MYSQL_PASSWORD:
                    node[key] = MYSQL_PASSWORD
                elif is_pg and PG_PASSWORD:
                    node[key] = PG_PASSWORD
            else:
                _inject_credentials(value)
    elif isinstance(node, list):
        for item in node:
            _inject_credentials(item)


def _normalize_config(config: str) -> tuple[str, bool]:
    """把作业配置规范化为 2.3.x REST API 接受的格式。

    返回 (body, is_json)。当输入能解析为 JSON 对象时：
    - 把以单个对象给出的 source/sink/transform 包成数组
      （HOCON 文件用对象，但 REST API 强制要求数组）；
    - 并自动注入真实密码。
    """
    try:
        data = json.loads(config)
    except json.JSONDecodeError:
        return config, False  # HOCON 文本：原样提交
    if not isinstance(data, dict):
        return config, True
    for section in ("source", "transform", "sink"):
        value = data.get(section)
        if isinstance(value, dict):
            data[section] = [value]
    _inject_credentials(data)
    return json.dumps(data, ensure_ascii=False), True


def _fmt(response: httpx.Response) -> str:
    """把 HTTP 响应格式化为字符串：优先 JSON，失败则退回状态码+文本。"""
    try:
        return json.dumps(response.json(), ensure_ascii=False)
    except Exception:
        return f"HTTP {response.status_code}: {response.text[:500]}"


@mcp.tool()
def list_running_jobs() -> str:
    """列出当前正在运行的 SeaTunnel 同步作业（jobId、jobName、状态）。"""
    return _fmt(_client.get(f"{BASE_URL}/running-jobs"))


@mcp.tool()
def list_finished_jobs() -> str:
    """列出已结束的 SeaTunnel 作业及其最终状态（FINISHED/FAILED/CANCELED）。"""
    return _fmt(_client.get(f"{BASE_URL}/finished-jobs"))


@mcp.tool()
def get_job_info(job_id: str) -> str:
    """查询单个作业的详细信息：状态、指标（读取/写入条数）、错误信息。

    Args:
        job_id: 作业 ID（来自 submit_job 的返回或作业列表工具）
    """
    return _fmt(_client.get(f"{BASE_URL}/job-info/{job_id}"))


@mcp.tool()
def submit_job(job_config: str, job_name: str = "") -> str:
    """向 SeaTunnel Zeta 集群提交数据同步作业（JSON 配置）。

    本集群（SeaTunnel 2.3.13）已验证的规则：
    1. source/sink/transform 必须是插件对象的数组（JSON 格式时）。
    2. 每个插件必须有 "plugin_name"（如 "Jdbc"）。
    3. PostgreSQL sink：选项 "database" 既作为 URL 里的库名，
       又作为 SQL 里的 schema 前缀。因此目标 PG 库里必须存在同名
       schema（可先通过 postgres MCP 执行
       "CREATE SCHEMA IF NOT EXISTS <database>;"）。
    4. 不设置 schema_save_mode = "CREATE_SCHEMA_WHEN_NOT_EXIST"
       时目标表不会自动建表。
    5. 不要在 job_config 里写真实数据库密码。所有 password 字段
       一律写字面量占位符 "..."，MCP 服务器会自动注入真实凭据
       （MySQL 和 PostgreSQL 均支持）。
    6. 提交前必须向用户展示 source 查询和目标表，并获得确认。
    7. 向已存在的目标表重复提交同步会报 "table already exists"
       （SeaTunnel 2.3.13 PG catalog 的 bug）。重新同步同一张表前，
       需先通过 postgres MCP 的 execute_sql 工具 DROP 该表
       （并告知用户数据会被全量重新加载）。

    可用的示例（MySQL -> PostgreSQL）：

    {"env": {"job.mode": "BATCH", "parallelism": 1},
     "source": [{"plugin_name": "Jdbc",
       "url": "jdbc:mysql://10.131.102.145:3306/test",
       "driver": "com.mysql.cj.jdbc.Driver",
       "user": "root", "password": "...",
       "query": "SELECT id, name FROM tab01"}],
     "sink": [{"plugin_name": "Jdbc",
       "url": "jdbc:postgresql://10.131.102.145:5433/omop",
       "driver": "org.postgresql.Driver",
       "user": "omop", "password": "...",
       "database": "omop", "table": "tab01_sync",
       "primary_keys": ["id"], "generate_sink_sql": true,
       "schema_save_mode": "CREATE_SCHEMA_WHEN_NOT_EXIST",
       "data_save_mode": "APPEND_DATA"}]}

    同步到 Hive 的规则（原生 Hive connector，已验证可用）：
    8. sink 用 plugin_name "Hive"，必需选项只有两个：
       "metastore_uri"（固定值 thrift://10.131.102.144:30083）和
       "table_name"（格式必须是 "库.表"，如 "testdb.tab01_sync"）。
       不要用 hive_database_name/hive_table_name 等键名（会报
       "options('table_name') are required"）。
    9. 目标 Hive 表必须先建好（用 hive MCP 的 execute_sql 建，
       建议 CREATE TABLE ... STORED AS TEXTFILE，列类型与来源对齐），
       Hive connector 不会自动建表。
    10. 服务端已配置好 HDFS 访问权限（HADOOP_USER_NAME=hadoop）和
        hosts 解析，作业配置中无需任何 HDFS 相关参数。
    11. 重复同步同一张 Hive 表会追加新数据文件（append 语义）。
        需要全量重灌时，先经 hive MCP 用 execute_sql
        DROP 再重建表，或 TRUNCATE 后重新提交（须先向用户确认）。
    12. 不要走 jdbc:hive2:// 的 Jdbc sink 写 Hive（SeaTunnel 2.3.13
        明确不支持，且 Hive JDBC 驱动无 addBatch 能力）。

    可用的示例（MySQL -> Hive）：

    {"env": {"job.mode": "BATCH", "parallelism": 1},
     "source": [{"plugin_name": "Jdbc",
       "url": "jdbc:mysql://10.131.102.145:3306/test",
       "driver": "com.mysql.cj.jdbc.Driver",
       "user": "root", "password": "...",
       "query": "SELECT id, name FROM tab01"}],
     "sink": [{"plugin_name": "Hive",
       "metastore_uri": "thrift://10.131.102.144:30083",
       "table_name": "testdb.tab01_sync"}]}

    Args:
        job_config: 作业配置，JSON 对象字符串（也接受 HOCON 文本）
        job_name: 可选，便于阅读的作业名
    """
    if not job_config or not job_config.strip():
        return "ERROR: job_config 为空。请传入完整的作业配置 JSON 字符串。"
    body, is_json = _normalize_config(job_config)
    params = {"jobName": job_name} if job_name else {}
    headers = {"Content-Type": "application/json" if is_json else "text/plain"}
    resp = _client.post(
        f"{BASE_URL}/submit-job", content=body, headers=headers, params=params
    )
    return _fmt(resp)


@mcp.tool()
def stop_job(job_id: str) -> str:
    """停止一个正在运行的 SeaTunnel 作业（不生成 savepoint）。

    安全要求：停止非本次会话启动的作业前，必须先与用户确认。

    Args:
        job_id: 正在运行的作业 ID
    """
    return _fmt(
        _client.post(
            f"{BASE_URL}/stop-job",
            params={"jobId": job_id, "isStopWithSavePoint": "false"},
        )
    )


@mcp.tool()
def cluster_monitoring() -> str:
    """查询 SeaTunnel 集群负载（各节点 CPU/内存）——提交大型同步作业前建议先查看。"""
    return _fmt(_client.get(f"{BASE_URL}/system-monitoring-information"))


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
