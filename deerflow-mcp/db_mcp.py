"""DeerFlow MCP 服务器：MySQL / PostgreSQL / Trino / Hive 数据工具。

以 streamable-HTTP 方式运行的 MCP 服务器，通过环境变量切换行为：

    DB_TYPE     mysql | pg | trino | hive （必填）
    PORT        HTTP 监听端口             （默认 9101）
    DB_HOST / DB_PORT / DB_USER / DB_PASSWORD / DB_NAME   （mysql/pg 使用）
    TRINO_HOST / TRINO_PORT / TRINO_USER / TRINO_CATALOG （trino 使用）
    HIVE_HOST / HIVE_PORT / HIVE_USER / HIVE_AUTH         （hive 使用）
    ALLOW_WRITE true|false  （默认 true；开启后才暴露 execute_sql 工具）
"""

import os

from mcp.server.fastmcp import FastMCP

from db_common import is_readonly_sql, rows_to_json

DB_TYPE = os.environ.get("DB_TYPE", "mysql").lower()
ALLOW_WRITE = os.environ.get("ALLOW_WRITE", "true").lower() == "true"
PORT = int(os.environ.get("PORT", "9101"))

mcp = FastMCP(f"{DB_TYPE}-mcp", host="0.0.0.0", port=PORT)

# ── 连接与实现层（按 DB_TYPE 分支）────────────────────────────────────────────

if DB_TYPE == "mysql":
    import pymysql

    def connect(database: str | None = None):
        """建立 MySQL 连接，使用 DictCursor 游标。"""
        return pymysql.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", "3306")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=database or os.environ.get("DB_NAME"),
            cursorclass=pymysql.cursors.DictCursor,
            charset="utf8mb4",
            autocommit=True,
        )

    # MySQL 系统库，不对外展示
    MYSQL_SYSTEM_DBS = {"information_schema", "performance_schema", "mysql", "sys"}

    def _list_databases() -> str:
        """列出所有用户数据库（排除系统库）。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SHOW DATABASES")
            names = [r["Database"] for r in cur.fetchall()]
        names = [n for n in names if n not in MYSQL_SYSTEM_DBS]
        return rows_to_json([{"database": n} for n in names], max_rows=1000)

    def _list_tables(database: str) -> str:
        """列出指定库下的所有基本表，含近似行数与占用大小。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT TABLE_NAME AS table_name, TABLE_ROWS AS approx_rows, "
                "ROUND((DATA_LENGTH+INDEX_LENGTH)/1024/1024, 2) AS size_mb "
                "FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=%s AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME",
                (database,),
            )
            rows = cur.fetchall()
        return rows_to_json(rows, max_rows=1000)

    def _describe_table(database: str, table: str) -> str:
        """查询表结构：列定义 + 索引信息。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT COLUMN_NAME AS column_name, COLUMN_TYPE AS data_type, "
                "IS_NULLABLE AS nullable, COLUMN_KEY AS key_info, "
                "COLUMN_DEFAULT AS default_value, EXTRA AS extra "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
                (database, table),
            )
            cols = cur.fetchall()
            if not cols:
                return f"Table '{database}.{table}' not found."
            cur.execute(
                "SELECT INDEX_NAME AS index_name, COLUMN_NAME AS column_name, "
                "NON_UNIQUE AS non_unique FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
                (database, table),
            )
            idx = cur.fetchall()
        return rows_to_json(
            [{"columns": cols, "indexes": idx}], max_rows=1
        ).replace('"rows"', '"table"')

    def _read_query(sql: str, database: str | None) -> str:
        """执行只读查询并以 JSON 返回结果行。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(sql)
            return rows_to_json(cur.fetchall())

    def _execute_sql(sql: str, database: str | None) -> str:
        """执行写入/DDL 语句并返回影响行数。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(sql)
            return f"OK. affected_rows={cur.rowcount}"

elif DB_TYPE == "trino":
    import trino

    def connect(database: str | None = None):
        """建立 Trino 连接；database 参数格式为 catalog 或 catalog.schema。"""
        return trino.dbapi.connect(
            host=os.environ.get("TRINO_HOST", "10.131.102.144"),
            port=int(os.environ.get("TRINO_PORT", "8080")),
            user=os.environ.get("TRINO_USER", "admin"),
            catalog=(database or os.environ.get("TRINO_CATALOG", "system")).split(".")[0],
            schema=(database or "information_schema").split(".", 1)[1]
            if "." in (database or "") else None,
        )

    def _rows(cur):
        """把 Trino 游标结果转成字典列表。"""
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _list_databases() -> str:
        """列出所有 catalog（Trino 中对应"数据库"概念）。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SHOW CATALOGS")
            rows = [{"catalog": r[0]} for r in cur.fetchall()]
        return rows_to_json(rows, max_rows=1000)

    def _list_tables(database: str) -> str:
        """列出指定 catalog（或 catalog.schema）下的所有表。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(f"SHOW TABLES FROM {database}")
            rows = [{"table_name": r[0]} for r in cur.fetchall()]
        return rows_to_json(rows, max_rows=1000)

    def _describe_table(database: str, table: str) -> str:
        """查看表结构（列名、类型、是否分区键等）。"""
        full = f"{database}.{table}" if "." not in table and database else table
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(f"DESCRIBE {full}")
            rows = _rows(cur)
        if not rows:
            return f"Table '{full}' not found."
        return rows_to_json(rows, max_rows=200)

    def _read_query(sql: str, database: str | None) -> str:
        """执行只读 Trino SQL 并以 JSON 返回结果行。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(sql)
            return rows_to_json(_rows(cur))

    def _execute_sql(sql: str, database: str | None) -> str:
        """执行写入语句（默认被 ALLOW_WRITE=false 禁用）。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(sql)
            return f"OK. affected_rows={cur.rowcount}"

elif DB_TYPE == "hive":
    from impala.dbapi import connect as _hive_connect

    def connect(database: str | None = None):
        """建立 HiveServer2 连接（impyla 驱动）。"""
        return _hive_connect(
            host=os.environ.get("HIVE_HOST", "10.131.102.144"),
            port=int(os.environ.get("HIVE_PORT", "30000")),
            database=database or os.environ.get("DB_NAME", "default"),
            user=os.environ.get("HIVE_USER", "admin"),
            auth_mechanism=os.environ.get("HIVE_AUTH", "PLAIN"),
        )

    def _rows(cur):
        """把 Hive 游标结果转成字典列表。"""
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def _list_databases() -> str:
        """列出所有 Hive 数据库。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SHOW DATABASES")
            rows = [{"database": r[0]} for r in cur.fetchall()]
        return rows_to_json(rows, max_rows=1000)

    def _list_tables(database: str) -> str:
        """列出指定库下的所有表。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(f"SHOW TABLES IN {database}")
            rows = [{"table_name": r[0]} for r in cur.fetchall()]
        return rows_to_json(rows, max_rows=1000)

    def _describe_table(database: str, table: str) -> str:
        """查看表结构（列名、类型、注释）。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(f"DESCRIBE {database}.{table}")
            rows = _rows(cur)
        if not rows:
            return f"Table '{database}.{table}' not found."
        return rows_to_json(rows, max_rows=200)

    def _read_query(sql: str, database: str | None) -> str:
        """执行只读 HiveQL 并以 JSON 返回结果行。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(sql)
            return rows_to_json(_rows(cur))

    def _execute_sql(sql: str, database: str | None) -> str:
        """执行写入语句（默认被 ALLOW_WRITE=false 禁用）。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(sql)
            return f"OK. affected_rows={cur.rowcount}"

elif DB_TYPE == "pg":
    import psycopg

    def connect(database: str | None = None):
        """建立 PostgreSQL 连接，使用 dict_row 行工厂。"""
        return psycopg.connect(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", "5432")),
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            dbname=database or os.environ.get("DB_NAME", "postgres"),
            row_factory=psycopg.rows.dict_row,
        )

    # PostgreSQL 系统模式，不对外展示
    PG_SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")

    def _list_databases() -> str:
        """列出所有用户数据库（排除模板库和 postgres 库）。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT datname FROM pg_database "
                "WHERE NOT datistemplate AND datallowconn ORDER BY datname"
            )
            rows = cur.fetchall()
        names = [r["datname"] for r in rows if r["datname"] != "postgres"]
        return rows_to_json([{"database": n} for n in names], max_rows=1000)

    def _list_tables(database: str) -> str:
        """列出库下所有用户表（排除系统模式），含近似行数。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT table_schema, table_name, "
                "GREATEST(reltuples::bigint, 0) AS approx_rows "
                "FROM information_schema.tables t "
                "JOIN pg_class c ON c.relname = t.table_name "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "  AND n.nspname = t.table_schema "
                "WHERE t.table_type='BASE TABLE' "
                "AND t.table_schema <> ALL(%s) "
                "ORDER BY table_schema, table_name",
                (list(PG_SYSTEM_SCHEMAS),),
            )
            rows = [
                {
                    "table_schema": r["table_schema"],
                    "table_name": r["table_name"],
                    "approx_rows": r["approx_rows"],
                }
                for r in cur.fetchall()
            ]
        return rows_to_json(rows, max_rows=1000)

    def _describe_table(database: str, table: str) -> str:
        """查询表结构：列定义 + 索引信息；table 可带 schema 前缀（schema.table）。"""
        if "." in table:
            schema, rel = table.split(".", 1)
        else:
            schema, rel = "public", table
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, is_nullable AS nullable, "
                "column_default AS default_value, "
                "character_maximum_length AS max_len "
                "FROM information_schema.columns "
                "WHERE table_schema=%s AND table_name=%s "
                "ORDER BY ordinal_position",
                (schema, rel),
            )
            cols = cur.fetchall()
            if not cols:
                return f"Table '{database}.{schema}.{rel}' not found."
            cur.execute(
                "SELECT i.relname AS index_name, a.attname AS column_name, "
                "ix.indisunique AS is_unique, ix.indisprimary AS is_primary "
                "FROM pg_index ix "
                "JOIN pg_class t ON t.oid = ix.indrelid "
                "JOIN pg_class i ON i.oid = ix.indexrelid "
                "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey) "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname=%s AND t.relname=%s",
                (schema, rel),
            )
            idx = cur.fetchall()
        return rows_to_json(
            [{"columns": cols, "indexes": idx}], max_rows=1
        ).replace('"rows"', '"table"')

    def _read_query(sql: str, database: str | None) -> str:
        """执行只读查询并以 JSON 返回结果行。"""
        with connect(database) as conn, conn.cursor() as cur:
            cur.execute(sql)
            return rows_to_json(cur.fetchall())

    def _execute_sql(sql: str, database: str | None) -> str:
        """执行写入/DDL 语句，手动 commit 后返回影响行数。"""
        with connect() as conn, conn.cursor() as cur:
            cur.execute(sql)
            conn.commit()
            return f"OK. affected_rows={cur.rowcount}"

else:
    raise SystemExit(f"Unsupported DB_TYPE: {DB_TYPE}")


# ── MCP 工具定义 ──────────────────────────────────────────────────────────────

DIALECT = {
    "mysql": "MySQL",
    "pg": "PostgreSQL",
    "trino": "Trino SQL",
    "hive": "HiveQL",
}[DB_TYPE]


# 注意：带 .format()/f-string 的"docstring"不是字符串字面量，Python 不会把它
# 设为 __doc__，FastMCP 就拿不到工具描述。因此这三处先定义函数、显式赋
# __doc__，再用 mcp.tool() 手动注册。


def list_databases() -> str:
    return _list_databases()


list_databases.__doc__ = f"列出当前 {DIALECT} 服务器上的用户数据库（系统库已排除）。"
mcp.tool()(list_databases)


@mcp.tool()
def list_tables(database: str) -> str:
    """列出指定数据库下的所有基本表，含近似行数。

    Args:
        database: 数据库名（可用名称从 list_databases 获取）
    """
    return _list_tables(database)


def describe_table(database: str, table: str) -> str:
    return _describe_table(database, table)


describe_table.__doc__ = (
    "查看表结构：列定义（名称、类型、可空、默认值）及索引信息。\n\n"
    "Args:\n"
    "    database: 数据库名\n"
    "    table: 表名（"
    + (
        "PostgreSQL 非-public 模式请用 schema.table 形式"
        if DB_TYPE == "pg"
        else "直接使用表名"
    )
    + "）"
)
mcp.tool()(describe_table)


def read_query(sql: str, database: str | None = None) -> str:
    if not is_readonly_sql(sql):
        return (
            "REJECTED: read_query 仅接受单条 SELECT/WITH/SHOW/EXPLAIN/DESCRIBE 语句。"
            "DDL/DML 请使用 execute_sql（执行前须向用户展示语句并获得确认）。"
        )
    return _read_query(sql, database)


read_query.__doc__ = (
    f"执行只读查询（{DIALECT} 方言），结果以 JSON 返回。\n\n"
    "仅允许单条 SELECT / WITH / SHOW / EXPLAIN / DESCRIBE 语句。\n"
    "结果最多返回 200 行。请总是限定表名（db.table"
    + (" 或 schema.table" if DB_TYPE == "pg" else "")
    + "），或者通过 database 参数指定默认库。\n\n"
    "Args:\n"
    "    sql: 只读 SQL 语句\n"
    "    database: 可选，未限定表名时的默认数据库"
)
mcp.tool()(read_query)


@mcp.tool()
def execute_sql(sql: str, database: str | None = None) -> str:
    """执行写入/DDL 语句（INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/TRUNCATE）。

    安全要求：调用本工具前，必须先在对话中向用户展示完整 SQL 并获得
    明确确认。未经确认，禁止对本次会话中未创建的表执行 DROP/TRUNCATE。

    Args:
        sql: 单条 DDL/DML 语句
        database: 可选，默认数据库
    """
    if not ALLOW_WRITE:
        return "REJECTED: 当前 MCP 服务器以 ALLOW_WRITE=false 模式运行。"
    if is_readonly_sql(sql):
        return "这是只读语句，请改用 read_query。"
    return _execute_sql(sql, database)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
