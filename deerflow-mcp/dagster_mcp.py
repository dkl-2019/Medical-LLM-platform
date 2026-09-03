"""DeerFlow MCP 服务器：Dagster 编排调度工具。

封装 Dagster webserver 的 GraphQL API（本环境为 Dagster 1.13.12），
让对话式 Agent 可以查看资产/作业、触发物化、跟踪运行状态、终止运行。

环境变量：
    DAGSTER_URL  webserver GraphQL 地址（默认 http://10.131.102.145:3000/graphql）
    PORT         HTTP 监听端口（默认 9109）
"""

import json
import os

import httpx
from mcp.server.fastmcp import FastMCP

GQL_URL = os.environ.get("DAGSTER_URL", "http://10.131.102.145:3000/graphql").rstrip("/")
PORT = int(os.environ.get("PORT", "9109"))

# 代码位置与仓库名（medgov 平台固定部署）
LOCATION = os.environ.get("DAGSTER_LOCATION", "medgov")
REPOSITORY = os.environ.get("DAGSTER_REPOSITORY", "__repository__")

mcp = FastMCP("dagster-mcp", host="0.0.0.0", port=PORT)

_client = httpx.Client(timeout=60.0)


def _gql(query: str, variables: dict | None = None) -> str:
    """执行 GraphQL 请求，返回紧凑 JSON；出错时返回错误摘要。"""
    try:
        resp = _client.post(GQL_URL, json={"query": query, "variables": variables or {}})
        data = resp.json()
        if data.get("errors"):
            # GraphQL 层面的错误（查询不合法、对象不存在等）
            msgs = "; ".join(e.get("message", "")[:200] for e in data["errors"])
            return json.dumps({"error": msgs}, ensure_ascii=False)
        return json.dumps(data.get("data"), ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


@mcp.tool()
def dagster_overview() -> str:
    """一次性获取 Dagster 全貌：代码位置、作业、资产、最近运行。

    适合作为对话的第一个入口，先了解平台上有什么，再决定物化哪个资产。
    """
    q = """
    {
      repositoriesOrError {
        ... on RepositoryConnection { nodes { name location { name } } }
      }
      assetsOrError {
        ... on AssetConnection { nodes { key { path } definition { description } } }
      }
      runsFeedOrError(limit: 10, view: RUNS) {
        ... on RunsFeedConnection {
          results { ... on Run { runId jobName status } }
        }
      }
    }
    """
    return _gql(q)


@mcp.tool()
def list_assets() -> str:
    """列出所有资产（asset）：key、描述。资产是 Dagster 中数据/计算的基本单元。"""
    q = """
    {
      assetsOrError {
        ... on AssetConnection {
          nodes { key { path } definition { description } }
        }
      }
    }
    """
    return _gql(q)


@mcp.tool()
def list_runs(limit: int = 20) -> str:
    """列出最近的运行记录（runId、作业名、状态）。

    Args:
        limit: 最多返回条数（默认 20）
    """
    q = """
    query($limit: Int!) {
      runsFeedOrError(limit: $limit, view: RUNS) {
        ... on RunsFeedConnection {
          results { ... on Run { runId jobName status } }
        }
      }
    }
    """
    return _gql(q, {"limit": max(1, min(limit, 100))})


@mcp.tool()
def get_run_details(run_id: str) -> str:
    """查询单次运行的详情：状态、各步骤执行结果、标签、物化统计。

    Args:
        run_id: 运行 ID（来自 list_runs 或 materialize_assets 的返回）
    """
    q = """
    query($id: ID!) {
      runOrError(runId: $id) {
        ... on Run {
          runId jobName status
          creationTime startTime endTime
          tags { key value }
          stats { ... on RunStatsSnapshot { stepsFailed materializations } }
          stepStats { stepKey status }
        }
        ... on RunNotFoundError { message }
        ... on PythonError { message }
      }
    }
    """
    return _gql(q, {"id": run_id})


@mcp.tool()
def materialize_assets(asset_keys: list[str], note: str = "") -> str:
    """物化（materialize）指定的资产：触发 Dagster 运行其计算并产出数据。

    经由平台默认资产作业 __ASSET_JOB 提交，asset_selection 标签限定资产范围。
    提交后处于 QUEUED 状态，由 daemon 调度执行；可用 get_run_details 跟踪。

    Args:
        asset_keys: 要物化的资产 key 列表（可用名称从 list_assets 获取），
                    如 ["m0_heartbeat"]
        note: 可选备注，会写入运行标签方便追溯
    """
    if not asset_keys:
        return "ERROR: asset_keys 不能为空。资产名称请从 list_assets 获取。"
    # 通过 dagster/asset_selection 标签限定本次物化的资产范围
    tags = [{"key": "dagster/asset_selection", "value": json.dumps(asset_keys)}]
    if note:
        tags.append({"key": "deerflow/note", "value": note[:200]})
    q = """
    mutation($params: ExecutionParams!) {
      launchRun(executionParams: $params) {
        __typename
        ... on LaunchRunSuccess { run { runId status } }
        ... on RunConfigValidationInvalid { errors { message } }
        ... on PipelineNotFoundError { message }
        ... on PythonError { message }
      }
    }
    """
    params = {
        "selector": {
            "repositoryLocationName": LOCATION,
            "repositoryName": REPOSITORY,
            "jobName": "__ASSET_JOB",
        },
        "executionMetadata": {"tags": tags},
    }
    return _gql(q, {"params": params})


@mcp.tool()
def launch_job(job_name: str, run_config_yaml: str = "") -> str:
    """启动一个已定义的作业（job），可附带运行配置。

    Args:
        job_name: 作业名（可用名称从 dagster_overview 获取）
        run_config_yaml: 可选的运行配置（YAML 字符串），作业需要
                         配置（ops/resources）时传入
    """
    if not job_name or not job_name.strip():
        return "ERROR: job_name 不能为空。"
    q = """
    mutation($params: ExecutionParams!) {
      launchRun(executionParams: $params) {
        __typename
        ... on LaunchRunSuccess { run { runId status } }
        ... on RunConfigValidationInvalid { errors { message } }
        ... on PipelineNotFoundError { message }
        ... on PythonError { message }
      }
    }
    """
    params = {
        "selector": {
            "repositoryLocationName": LOCATION,
            "repositoryName": REPOSITORY,
            "jobName": job_name.strip(),
        },
    }
    if run_config_yaml and run_config_yaml.strip():
        # webserver 接受 YAML 字符串形式的运行配置
        params["runConfigData"] = run_config_yaml
    return _gql(q, {"params": params})


@mcp.tool()
def terminate_run(run_id: str) -> str:
    """终止一个正在运行/排队中的 Dagster 运行。

    安全要求：终止非本次会话启动的运行前，必须先与用户确认。

    Args:
        run_id: 运行 ID
    """
    if not run_id or not run_id.strip():
        return "ERROR: run_id 不能为空。"
    q = """
    mutation($id: String!) {
      terminateRun(runId: $id) {
        __typename
        ... on TerminateRunSuccess { run { runId status } }
        ... on RunNotFoundError { message }
        ... on PythonError { message }
      }
    }
    """
    return _gql(q, {"id": run_id.strip()})


@mcp.tool()
def reload_workspace() -> str:
    """重新加载代码位置（code location）。

    在 Dagster 作业/资产代码变更后调用，让 webserver 感知新定义。
    """
    q = """
    mutation($name: String!) {
      reloadRepositoryLocation(repositoryLocationName: $name) {
        __typename
        ... on ReloadLocationSuccess { message }
        ... on ReloadNotSupported { message }
        ... on PythonError { message }
      }
    }
    """
    return _gql(q, {"name": LOCATION})


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
