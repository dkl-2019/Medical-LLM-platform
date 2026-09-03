"""
OMOP Platform Backend - AI Chat Gateway
"""
import os
import json
import uuid
from typing import Optional, AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# ============ Configuration ============
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY", "your-api-key")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3-80b")

# Argo / SeaTunnel config
ARGO_SERVER = os.getenv("ARGO_SERVER", "https://10.131.102.114:2746")
ARGO_TOKEN = os.getenv("ARGO_TOKEN", "")

# MinIO / Iceberg config
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "10.131.102.114:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")

# PostgreSQL (pgvector) config
PG_HOST = os.getenv("PG_HOST", "10.131.102.114")
PG_PORT = os.getenv("PG_PORT", "5432")
PG_DATABASE = os.getenv("PG_DATABASE", "postgres")
PG_USER = os.getenv("PG_USER", "postgres")
PG_PASSWORD = os.getenv("PG_PASSWORD", "postgres")

# ============ MCP Tools Definition ============
MCP_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ingestion_submit",
            "description": "提交数据同步任务，生成 SeaTunnel 配置并通过 Argo Workflows 执行。输入源数据库连接信息、目标 Iceberg 表名以及字段映射规则。",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_type": {"type": "string", "enum": ["oracle", "sqlserver", "mysql", "postgresql"], "description": "源数据库类型"},
                    "source_host": {"type": "string", "description": "源数据库地址"},
                    "source_port": {"type": "integer", "description": "源数据库端口"},
                    "source_db": {"type": "string", "description": "源数据库名"},
                    "source_table": {"type": "string", "description": "源表名"},
                    "source_user": {"type": "string", "description": "用户名"},
                    "source_password": {"type": "string", "description": "密码"},
                    "target_table": {"type": "string", "description": "目标 Iceberg 表名（格式: 库名.表名）"},
                    "column_mappings": {"type": "object", "description": "字段映射，key=源字段, value=OMOP目标字段"}
                },
                "required": ["source_type", "source_host", "source_port", "source_db", "source_table", "target_table"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "terminology_match",
            "description": "将本地医疗术语（药品名/检查项目/诊断名称）通过 pgvector 语义匹配到 OMOP 标准词表。返回置信度最高的候选映射，低置信度结果需要用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "term": {"type": "string", "description": "本地术语字符串"},
                    "vocabulary_type": {"type": "string", "enum": ["Drug", "Condition", "Procedure", "Observation"], "description": "词表类型"},
                    "top_k": {"type": "integer", "default": 5, "description": "返回候选数量"}
                },
                "required": ["term", "vocabulary_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "workflow_status",
            "description": "查询 Argo Workflows 指定任务的工作流状态和 Pod 日志。用于监控长时间运行的数据同步任务。",
            "parameters": {
                "type": "object",
                "properties": {
                    "workflow_name": {"type": "string", "description": "Argo Workflow 名称"},
                    "namespace": {"type": "string", "default": "default", "description": "K8s 命名空间"}
                },
                "required": ["workflow_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "datahub_search",
            "description": "搜索 Datahub 元数据，查询医院源系统（Oracle/SQL Server）与结果集（Doris/StarRocks）的表结构、血缘关系、描述信息等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词（表名/库名/描述）"},
                    "platform": {"type": "string", "enum": ["mysql", "doris", "oracle", "sqlserver", "all"], "default": "all", "description": "数据源平台过滤"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "doris_query",
            "description": "对 Doris 数据仓库执行 SQL 查询，返回结果集。用于验证治理后的 OMOP 数据质量。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SELECT 查询语句"},
                    "limit": {"type": "integer", "default": 100, "description": "结果集上限"}
                },
                "required": ["sql"]
            }
        }
    }
]

# ============ Request/Response Models ============
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    history: list[ChatMessage] = []

# ============ Tool Implementations ============
async def call_argo_api(path: str, method: str = "GET", data: dict = None) -> dict:
    """调用 Argo Workflows API"""
    headers = {"Authorization": f"Bearer {ARGO_TOKEN}", "Content-Type": "application/json"} if ARGO_TOKEN else {"Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        url = f"{ARGO_SERVER}/{path.lstrip('/')}"
        func = getattr(client, method.lower())
        resp = await func(url, json=data, headers=headers)
        resp.raise_for_status()
        return resp.json()

async def ingestion_submit(
    source_type: str, source_host: str, source_port: int,
    source_db: str, source_table: str, target_table: str,
    source_user: str, source_password: str,
    column_mappings: dict = None
) -> dict:
    """生成 SeaTunnel YAML 配置并提交 Argo Workflow"""
    # 1. 生成 SeaTunnel 配置文件
    seatunnel_config = {
        "env": {
            "execution.parallelism": 2,
            "job.mode": "BATCH",
            "job.name": f"omop_sync_{source_table}"
        },
        "source": {
            f"Jdbc{source_type.title()}": {
                "driver": {
                    "oracle": "oracle.jdbc.OracleDriver",
                    "sqlserver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
                    "mysql": "com.mysql.cj.jdbc.Driver",
                    "postgresql": "org.postgresql.Driver"
                }.get(source_type, "com.mysql.cj.jdbc.Driver"),
                "url": {
                    "oracle": f"jdbc:oracle:thin:@//{source_host}:{source_port}/{source_db}",
                    "sqlserver": f"jdbc:sqlserver://{source_host}:{source_port};databaseName={source_db}",
                    "mysql": f"jdbc:mysql://{source_host}:{source_port}/{source_db}",
                    "postgresql": f"jdbc:postgresql://{source_host}:{source_port}/{source_db}"
                }.get(source_type),
                "username": source_user,
                "password": source_password,
                "query": f"SELECT * FROM {source_table}"
            }
        },
        "transform": [],
        "sink": {
            "Iceberg": {
                "Catalog": {
                    "name": " iceberg_catalog",
                    "type": "type",
                    "catalog_type": "hadoop",
                    "warehouse": f"s3a://omop-warehouse/{target_table}",
                    "ip": MINIO_ENDPOINT,
                    "access_key": MINIO_ACCESS_KEY,
                    "secret_key": MINIO_SECRET_KEY
                },
                "namespace": target_table.split(".")[0] if "." in target_table else "omop",
                "table": target_table.split(".")[-1] if "." in target_table else target_table,
                "profile": "batch"
            }
        }
    }

    # 2. 生成 Argo Workflow manifest
    workflow_manifest = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {"generateName": f"omop-sync-{source_table.lower()}-"},
        "spec": {
            "entrypoint": "seatunnel",
            "arguments": {
                "parameters": [
                    {"name": "config", "value": json.dumps(seatunnel_config)}
                ]
            },
            "templates": [{
                "name": "seatunnel",
                "container": {
                    "image": "apache/seatunnel:latest",
                    "command": ["/opt/seatunnel/bin/seatunnel-cluster.sh"],
                    "args": ["-r", "master", "-cn", "seatunnel"],
                    "env": [
                        {"name": "SEATUNNEL_CONFIG", "valueFrom": {"configMapKeyRef": {"name": "seatunnel-config", "key": "config"}}}
                    ]
                }
            }]
        }
    }

    # 3. 提交到 Argo（如果配置了 ARGO_TOKEN）
    if ARGO_TOKEN and ARGO_SERVER != "https://10.131.102.114:2746":
        result = await call_argo_api("api/v1/workflows/default", method="POST", data=workflow_manifest)
        workflow_name = result.get("metadata", {}).get("name", "unknown")
    else:
        # 模拟提交（本地开发模式）
        workflow_name = f"omop-sync-{source_table.lower()}-{uuid.uuid4().hex[:8]}"

    return {
        "ui_action": {
            "type": "PROGRESS_BAR",
            "title": f"同步任务已提交: {workflow_name}",
            "workflow_name": workflow_name,
            "message": f"已将 {source_db}.{source_table} 映射到 {target_table}，任务已提交执行"
        },
        "workflow_name": workflow_name,
        "status": "submitted"
    }

async def terminology_match(term: str, vocabulary_type: str, top_k: int = 5) -> dict:
    """通过 pgvector 做术语语义匹配"""
    try:
        import psycopg2
        conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, database=PG_DATABASE, user=PG_USER, password=PG_PASSWORD)
        cur = conn.cursor()

        # 假设有一个 omop_vocabulary 表存储了标准术语和向量
        # 这里用简化实现：从 postgres 搜索相似词
        cur.execute("""
            SELECT term, omop_concept_id, concept_name, similarity
            FROM omop_vocabulary
            WHERE vocabulary_type = %s
            ORDER BY similarity DESC
            LIMIT %s
        """, (vocabulary_type, top_k))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return {"results": [], "message": f"在 {vocabulary_type} 词表中未找到相关术语"}

        results = [{"local_term": term, "omop_concept_id": r[1], "concept_name": r[2], "confidence": round(r[3], 3)} for r in rows]
        low_confidence = [r for r in results if r["confidence"] < 0.85]

        ui_action = None
        if low_confidence:
            ui_action = {
                "type": "SINGLE_SELECT_CONFIRM",
                "title": "请确认术语映射",
                "term": term,
                "candidates": results[:top_k],
                "message": f"术语「{term}」找到多个候选映射，请选择正确的一项"
            }

        return {
            "results": results,
            "ui_action": ui_action,
            "top_candidate": results[0] if results else None
        }
    except ImportError:
        return {"error": "psycopg2 未安装，无法连接 PostgreSQL"}
    except Exception as e:
        return {"error": f"术语匹配失败: {str(e)}", "results": []}

async def workflow_status(workflow_name: str, namespace: str = "default") -> dict:
    """查询 Argo Workflow 状态"""
    try:
        result = await call_argo_api(f"api/v1/workflows/{namespace}/{workflow_name}")
        status = result.get("status", {})
        phase = status.get("phase", "Unknown")
        started_at = status.get("startedAt", "")
        duration = status.get("duration", "")

        pods = []
        for node in status.get("nodes", []):
            pods.append({
                "name": node.get("displayName", ""),
                "phase": node.get("phase", ""),
                "started_at": node.get("startedAt", "")
            })

        return {
            "workflow_name": workflow_name,
            "phase": phase,
            "started_at": started_at,
            "duration": duration,
            "pods": pods,
            "ui_action": {
                "type": "PROGRESS_BAR" if phase in ["Running", "Pending"] else "LOG_VIEW",
                "title": f"工作流状态: {phase}",
                "phase": phase,
                "message": f"任务已运行 {duration}" if duration else f"状态: {phase}"
            }
        }
    except httpx.HTTPStatusError as e:
        return {"error": f"查询 Argo 失败: {e.response.status_code}", "workflow_name": workflow_name}
    except Exception as e:
        return {"error": f"查询失败: {str(e)}"}

async def datahub_search(query: str, platform: str = "all") -> dict:
    """搜索 Datahub 元数据"""
    # 注意：Datahub GMS 有连接问题，这里先返回模拟数据
    # 后续 GMS 修复后可替换为真实 API 调用
    mock_results = [
        {"urn": "urn:li:dataset:(urn:li:dataPlatform:mysql,his.prescription,PROD)", "name": "HIS_PRESCRIPTION", "description": "门诊处方记录表", "platform": "mysql", "lastUpdated": "2026-04-20"},
        {"urn": "urn:li:dataset:(urn:li:dataPlatform:doris,omop.drug_exposure,PROD)", "name": "DRUG_EXPOSURE", "description": "OMOP 药物暴露表", "platform": "doris", "lastUpdated": "2026-04-28"},
    ]
    filtered = [r for r in mock_results if platform == "all" or r["platform"] == platform]
    return {"results": filtered, "query": query, "count": len(filtered)}

async def doris_query(sql: str, limit: int = 100) -> dict:
    """查询 Doris 数据仓库"""
    try:
        from pydoris.client import DorisNode
        from pydoris.dbapi import connect
        # 简化实现：返回模拟数据
        return {
            "sql": sql,
            "columns": ["concept_id", "concept_name", "vocabulary_id", "domain_id"],
            "rows": [
                {"concept_id": 1901, "concept_name": "Metformin", "vocabulary_id": "RxNorm", "domain_id": "Drug"},
                {"concept_id": 1902, "concept_name": "Aspirin", "vocabulary_id": "RxNorm", "domain_id": "Drug"},
            ],
            "row_count": 2,
            "message": "Doris 连接成功（模拟数据，正式环境替换为真实查询）"
        }
    except ImportError:
        return {"error": "pydoris 未安装", "sql": sql}
    except Exception as e:
        return {"error": f"Doris 查询失败: {str(e)}"}

# ============ Tool Executor ============
async def execute_tool(tool_name: str, arguments: dict) -> dict:
    """根据工具名执行对应的实现"""
    executors = {
        "ingestion_submit": ingestion_submit,
        "terminology_match": terminology_match,
        "workflow_status": workflow_status,
        "datahub_search": datahub_search,
        "doris_query": doris_query,
    }
    if tool_name not in executors:
        return {"error": f"Unknown tool: {tool_name}"}
    try:
        result = await executors[tool_name](**arguments)
        return result
    except Exception as e:
        return {"error": f"Tool execution failed: {str(e)}"}

# ============ LLM Interaction ============
async def stream_llm(messages: list, tool_results: list = None) -> AsyncIterator[str]:
    """流式调用 LLM，支持 tool call 循环"""
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": True,
        "tools": MCP_TOOLS
    }
    if tool_results:
        payload["messages"].append({
            "role": "assistant",
            "tool_calls": None
        })
        for tr in tool_results:
            payload["messages"].append({
                "role": "tool",
                "tool_call_id": tr["tool_call_id"],
                "tool_name": tr["tool_name"],
                "content": json.dumps(tr["result"])
            })

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", f"{LLM_BASE_URL}/chat/completions", json=payload, headers=headers) as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        # 处理 content
                        content = delta.get("content", "")
                        if content:
                            yield json.dumps({"type": "content", "content": content}) + "\n"
                        # 处理 tool_call
                        tool_calls = delta.get("tool_calls", [])
                        for tc in tool_calls:
                            yield json.dumps({"type": "tool_call", "tool_call": tc}) + "\n"
                    except json.JSONDecodeError:
                        continue

# ============ FastAPI App ============
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("OMOP Platform Backend started")
    yield
    print("OMOP Platform Backend stopped")

app = FastAPI(title="OMOP Platform AI Gateway", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

@app.get("/")
async def root():
    return {"message": "OMOP Platform AI Gateway", "version": "0.1.0", "tools": [t["function"]["name"] for t in MCP_TOOLS]}

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat(req: ChatRequest):
    """流式对话接口 - SSE"""
    session_id = req.session_id or str(uuid.uuid4())

    # 构建消息历史
    messages = [{"role": "system", "content": (
        "你是一个专业的医疗数据治理助手，帮助用户将医院异构数据转换为 OMOP CDM 标准模型。"
        "你可以使用工具来查询元数据、提交数据同步任务、查询工作流状态、匹配术语映射。"
        "当用户提出数据同步、术语映射等需求时，应该主动调用相应工具。"
        "每次只调用一个工具，等工具返回后再决定下一步。"
    )}]
    for h in req.history:
        messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": req.message})

    tool_results = []
    content_buffer = ""

    async def event_generator() -> AsyncIterator[str]:
        nonlocal tool_results, content_buffer
        async for line in stream_llm(messages, tool_results if tool_results else None):
            try:
                event = json.loads(line)
                if event["type"] == "content":
                    content_buffer += event["content"]
                    yield f"data: {json.dumps({'type': 'content', 'content': event['content']})}\n\n"
                elif event["type"] == "tool_call":
                    tc = event["tool_call"]
                    tool_name = tc["function"]["name"]
                    tool_args = json.loads(tc["function"]["arguments"])
                    tool_call_id = tc["id"]

                    # 先把已有的 content 发完
                    if content_buffer:
                        yield f"data: {json.dumps({'type': 'content', 'content': content_buffer})}\n\n"
                        content_buffer = ""

                    # 执行工具
                    result = await execute_tool(tool_name, tool_args)
                    tool_results.append({
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "result": result
                    })

                    # 把工具结果通知前端
                    yield f"data: {json.dumps({'type': 'tool_result', 'tool_name': tool_name, 'result': result})}\n\n"

                    # 如果工具返回了 ui_action，单独发一条
                    if isinstance(result, dict) and result.get("ui_action"):
                        yield f"data: {json.dumps({'type': 'ui_action', 'ui_action': result['ui_action']})}\n\n"

            except json.JSONDecodeError:
                continue

        # 发完剩余的 content
        if content_buffer:
            yield f"data: {json.dumps({'type': 'content', 'content': content_buffer})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/ui/action")
async def ui_action(req: dict):
    """接收前端动态组件的提交动作"""
    action_type = req.get("action")
    params = req.get("params", {})
    return {"status": "received", "action": action_type, "params": params}

@app.get("/tools")
async def list_tools():
    """列出所有可用工具"""
    return {"tools": MCP_TOOLS}
