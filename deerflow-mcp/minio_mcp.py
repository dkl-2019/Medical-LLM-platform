"""DeerFlow MCP 服务器：MinIO / S3 对象存储工具。

环境变量：
    MINIO_ENDPOINT   地址 host:port（默认 10.131.102.145:9000）
    MINIO_ACCESS_KEY / MINIO_SECRET_KEY  访问凭据
    PORT             HTTP 监听端口（默认 9104）
"""

import io
import json
import os

from minio import Minio
from mcp.server.fastmcp import FastMCP

ENDPOINT = os.environ.get("MINIO_ENDPOINT", "10.131.102.145:9000")
ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "")
PORT = int(os.environ.get("PORT", "9104"))

mcp = FastMCP("minio-mcp", host="0.0.0.0", port=PORT)

_client = Minio(ENDPOINT, access_key=ACCESS_KEY, secret_key=SECRET_KEY, secure=False)


@mcp.tool()
def list_buckets() -> str:
    """列出所有桶（bucket）及创建时间。"""
    buckets = [
        {"bucket": b.name, "created": b.creation_date}
        for b in _client.list_buckets()
    ]
    # default=str：MinIO 返回的 datetime 无法直接 JSON 序列化
    return json.dumps(buckets, ensure_ascii=False, default=str)


@mcp.tool()
def list_objects(bucket: str, prefix: str = "", max_keys: int = 100) -> str:
    """列出桶内的对象。

    Args:
        bucket: 桶名
        prefix: 可选，对象 key 前缀过滤（类似文件夹路径）
        max_keys: 最多返回对象数（默认 100）
    """
    try:
        objs = []
        for obj in _client.list_objects(bucket, prefix=prefix, recursive=True):
            objs.append(
                {
                    "key": obj.object_name,
                    "size_bytes": obj.size,
                    "last_modified": obj.last_modified.isoformat()
                    if obj.last_modified
                    else None,
                }
            )
            if len(objs) >= max_keys:
                break
        return json.dumps(
            {"bucket": bucket, "prefix": prefix, "count": len(objs), "objects": objs},
            ensure_ascii=False,
        )
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
def read_text_object(bucket: str, key: str, max_bytes: int = 32768) -> str:
    """读取文本类对象（csv/json/sql/log 等）的内容。

    Args:
        bucket: 桶名
        key: 对象 key（精确 key 请从 list_objects 获取）
        max_bytes: 读取上限，默认 32KB
    """
    try:
        response = _client.get_object(bucket, key)
        data = response.read(max_bytes + 1)
        truncated = len(data) > max_bytes
        text = data[:max_bytes].decode("utf-8", errors="replace")
        return text + ("\n...[已截断]" if truncated else "")
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
def put_text_object(bucket: str, key: str, content: str) -> str:
    """把文本内容（csv/json/报告/sql 等）写入 MinIO 新对象。

    桶必须已存在。

    Args:
        bucket: 桶名
        key: 对象 key，例如 reports/summary-20260818.json
        content: 完整文本内容
    """
    try:
        data = content.encode("utf-8")
        _client.put_object(
            bucket, key, io.BytesIO(data), length=len(data),
            content_type="application/octet-stream",
        )
        return f"OK. 已写入 s3://{bucket}/{key}（{len(data)} 字节）"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
def delete_object(bucket: str, key: str) -> str:
    """删除单个对象。

    安全要求：删除非本次会话创建的对象前，必须先与用户确认。

    Args:
        bucket: 桶名
        key: 对象 key
    """
    try:
        _client.remove_object(bucket, key)
        return f"OK. 已删除 s3://{bucket}/{key}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


@mcp.tool()
def presigned_url(bucket: str, key: str, expires_hours: int = 24) -> str:
    """为对象生成临时可分享的下载链接。

    Args:
        bucket: 桶名
        key: 对象 key
        expires_hours: 链接有效期（小时，默认 24）
    """
    from datetime import timedelta

    try:
        url = _client.presigned_get_object(
            bucket, key, expires=timedelta(hours=expires_hours)
        )
        return f"http://{ENDPOINT}{url}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
