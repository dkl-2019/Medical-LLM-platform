# DeerFlow + MCP 数据同步平台：开发、测试、验证全记录

> 日期：2026-08-18
> 服务器：10.131.102.145（离线内网环境，Docker 部署）
> 状态：端到端验证通过（对话 -> 查源表结构 -> 生成 SeaTunnel 作业 -> 自动建表 -> 数据同步 -> 行数校验）

---

## 1. 整体架构

```
用户对话
  └─ DeerFlow 2.0 (http://10.131.102.145:2026)
       │  Agent 编排，通过 MCP (streamable-http) 调用工具
       ├─ mysql-mcp      :9101 ──> MySQL 8        :3306 (库: his_demo, test)
       ├─ postgres-mcp   :9102 ──> PostgreSQL      :5433 (库: omop)
       └─ seatunnel-mcp  :9103 ──> SeaTunnel 2.3.13 :8080 (Zeta REST API)
```

| 组件 | 容器 | 镜像/代码位置 |
|------|------|--------------|
| DeerFlow 前端/网关/入口 | deer-flow-frontend / gateway / nginx / redis | /data/deer-flow（源码 + config.yaml + .env + extensions_config.json） |
| MCP server x3 | deerflow-mcp-mysql / -pg / -seatunnel | /data/deerflow-mcp（自研 Python，FastMCP） |
| MySQL | medgov-mysql-poc-1 | root / CHANGE_ME_mysql |
| PostgreSQL | medgov-pg-omop-1 | omop / CHANGE_ME_pg_omop，库 omop |
| SeaTunnel | medgov-seatunnel-1 | apache/seatunnel:2.3.13，REST :8080 |

---

## 2. MCP 开发

### 2.1 技术选型

- **框架**：Python `mcp` SDK 1.x 的 `FastMCP`（注意：**必须锁 `<2.0.0`**，2.0 移除了 `mcp.server.fastmcp` 模块路径）
- **传输**：`streamable-http`（独立容器常驻，路径 `/mcp`），比 stdio 好部署、好监控、好复用
- **依赖**：`mcp>=1.2.0,<2.0.0`、`httpx`、`pymysql`（MySQL）、`psycopg[binary]`（PG）
- **客户端集成**：DeerFlow 走 `langchain-mcp-adapters`，`extensions_config.json` 里 `type: "http"` + url 即可

### 2.2 代码结构（/data/deerflow-mcp）

```
db_common.py        共享：SQL 只读校验(正则)、行数截断(200)、JSON 序列化
db_mcp.py           MySQL/PG 二合一 server，由 DB_TYPE 环境变量区分行为
seatunnel_mcp.py    SeaTunnel Zeta REST 封装
Dockerfile          python:3.12-slim + 清华 pypi
docker-compose.yml  三个服务：mcp-mysql(9101) / mcp-pg(9102) / mcp-seatunnel(9103)
```

### 2.3 工具清单（16 个）

**mysql-mcp / postgres-mcp（各 5 个）**

| 工具 | 说明 | 安全设计 |
|------|------|---------|
| `list_databases` | 列用户库（排除系统库） | 只读 |
| `list_tables(database)` | 列表 + 估算行数 | 只读 |
| `describe_table(database, table)` | 列定义 + 索引 | 只读 |
| `read_query(sql)` | 查询，返回 JSON | **正则强制单条 SELECT/WITH/SHOW/EXPLAIN/DESCRIBE**，含分号多语句直接拒绝，结果截 200 行 |
| `execute_sql(sql)` | DDL/DML | 工具描述要求 Agent 必须先向用户展示 SQL 并确认；`ALLOW_WRITE=false` 可整体关闭 |

**seatunnel-mcp（6 个）**

| 工具 | 说明 |
|------|------|
| `submit_job(job_config, job_name)` | 提交同步作业（内置格式自动纠正 + 密码注入，见下） |
| `stop_job(job_id)` | 停止作业（要求先确认） |
| `list_running_jobs` / `list_finished_jobs` | 作业列表及状态 |
| `get_job_info(job_id)` | 作业详情：状态、读写计数、错误 |
| `cluster_monitoring` | 集群负载 |

### 2.4 submit_job 的三层防御（本次踩坑的结晶）

1. **格式自动纠正**：JSON 里 `source`/`sink`/`transform` 传了对象（HOCON 风格）自动包成数组——REST API 只认数组
2. **密码自动注入**：password 字段为 `...`/`***`/`******`/`$MYSQL_PASSWORD` 等占位符时，按同级 `url` 判断方言，用容器环境变量 `MYSQL_PASSWORD`/`PG_PASSWORD` 替换——**模型永远不知道真实密码**，杜绝 `Access denied`
3. **工具描述内置规则**：数组格式、PG schema 要求、重复同步先删表、提交前向用户展示配置确认

### 2.5 DeerFlow 侧注册（热生效）

`/data/deer-flow/extensions_config.json`：

```json
{
  "mcpServers": {
    "mysql":     {"enabled": true, "type": "http", "url": "http://10.131.102.145:9101/mcp"},
    "postgres":  {"enabled": true, "type": "http", "url": "http://10.131.102.145:9102/mcp"},
    "seatunnel": {"enabled": true, "type": "http", "url": "http://10.131.102.145:9103/mcp"}
  },
  "skills": {}
}
```

要点：
- **改 MCP 配置热生效**（下次对话加载）；**改 config.yaml（模型配置）必须 `docker restart deer-flow-gateway`**
- 单文件 bind mount：编辑 extensions_config.json 要原地写（`cat >`），不要 `sed -i`/`mv`（会换 inode，容器里看不到新内容）
- 更新 MCP server 代码后：`docker compose up -d --build` + `docker restart deer-flow-gateway`（清工具缓存）

---

## 3. MySQL 接入流程（已验证）

1. MCP 容器环境变量：`DB_TYPE=mysql, DB_HOST/PORT/USER/PASSWORD`
2. 对话验证链：`list_databases` 返回 his_demo、test -> `describe_table(test, tab01)` 拿到 id/name/city 结构 -> Agent 据此生成同步作业的 source query
3. MySQL 侧给 SeaTunnel JDBC source 用的就是 root 账号（内网测试环境；生产建议专号）

## 4. PostgreSQL 接入流程（已验证，坑最多）

1. MCP 容器环境变量：`DB_TYPE=pg, DB_PORT=5433, DB_USER=omop, DB_NAME=omop`
2. psycopg3 参数化陷阱：`NOT IN %s` 元组不行，要用 `<> ALL(%s)` + list
3. **为 SeaTunnel 做的一次性准备（关键）**：
   ```sql
   CREATE SCHEMA IF NOT EXISTS omop;                          -- 库里建同名 schema
   ALTER DATABASE omop SET search_path TO omop, public;       -- 默认 search_path
   ```
   原因见第 6 节 PG sink 三大坑

## 5. SeaTunnel 接入流程（已验证）

### 5.1 REST API（2.3.13 实测可用端点，端口 8080）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/submit-job?jobName=x` | POST | body=作业 JSON，Content-Type: application/json |
| `/running-jobs` `/finished-jobs` | GET | 作业列表 |
| `/job-info/{jobId}` | GET | 详情/错误 |
| `/stop-job?jobId=x&isStopWithSavePoint=false` | POST | 停作业 |
| `/system-monitoring-information` | GET | 集群负载 |

注意：旧文档的 `/hazelcast/rest/maps/submit-job` 在 2.3.13 已 404，用上面的新路径。**不需要 CLI 客户端**，REST 全部搞定。

### 5.2 验证通过的完整作业配置（MySQL -> PG 模板）

```json
{
  "env": {"job.mode": "BATCH", "parallelism": 1},
  "source": [{
    "plugin_name": "Jdbc",
    "url": "jdbc:mysql://10.131.102.145:3306/test",
    "driver": "com.mysql.cj.jdbc.Driver",
    "user": "root",
    "password": "...",
    "query": "SELECT id, name, city FROM tab01"
  }],
  "sink": [{
    "plugin_name": "Jdbc",
    "url": "jdbc:postgresql://10.131.102.145:5433/omop",
    "driver": "org.postgresql.Driver",
    "user": "omop",
    "password": "...",
    "database": "omop",
    "table": "tab01_from_mysql",
    "primary_keys": ["id"],
    "generate_sink_sql": true,
    "schema_save_mode": "CREATE_SCHEMA_WHEN_NOT_EXIST",
    "data_save_mode": "APPEND_DATA"
  }]
}
```

（password 写 `...` 占位，MCP server 自动注入真实值）

### 5.3 验证结果

- 提交返回 `{"jobId": "...", "jobName": "..."}`
- 目标表**自动建表**（含主键）并写入 3 行，jobStatus=FINISHED
- 重复数据可幂等（`generate_sink_sql` + `primary_keys` 生成 upsert）

---

## 6. 踩坑记录（按时间线，全部已解决或已规避）

| # | 现象 | 根因 | 解决 |
|---|------|------|------|
| 1 | MCP 容器启动崩：`No module named 'mcp.server.fastmcp'` | pip 装了 mcp 2.0，模块路径变了 | requirements 锁 `mcp<2.0.0` |
| 2 | PG `list_tables` 报 `syntax error at or near "$1"` | psycopg3 不支持 `NOT IN %s` 元组展开 | 改 `<> ALL(%s)` + list |
| 3 | DeerFlow 提交作业报 config 参数缺失（`input_value={}`） | 模型偶发漏传参数 + 参数名 `config` 太通用 | 改名 `job_config` + 空参数返回明确错误提示（模型会自行重试修正） |
| 4 | REST 提交报 `LinkedHashMap cannot be cast to ArrayList` | JSON 格式下 source/sink **必须是数组**（HOCON 里是对象） | MCP server 自动把对象包成数组 |
| 5 | 作业 FAILED：`relation "omop.tab01_mysql_sync" does not exist` | PG sink 的 `database` 选项被同时用作 URL 库名和 SQL schema 前缀 | 库里 `CREATE SCHEMA omop`，让两边路径一致 |
| 6 | 作业 FAILED：`Failed creating table ... already exists` | SeaTunnel 2.3.13 PG catalog bug：存在性检查（走 search_path）与建表（database.schema 限定）看的路径不一致 | **遗留**：重复同步同一张表前先 DROP（已写进工具描述让 Agent 自动做）；新表首次同步不受影响 |
| 7 | 报 `Unable to create a source for identifier 'Jdbc'`（一度误判为插件未安装） | 外层包装错误。真实根因：`Access denied for user 'root'@'172.18.0.1'`——DeerFlow 不知道真实密码，填了占位符 | **MCP server 端密码注入**（占位符 -> 环境变量真实密码）。connector-jdbc-2.3.13.jar 一直都在，无需 install-plugin.sh |
| 8 | `IGNORE_SCHEMA` 等 save mode 值不识别 / 不传 save mode 默认也触发建表冲突 | 2.3.13 对这些枚举处理混乱 | 固化用 `CREATE_SCHEMA_WHEN_NOT_EXIST + APPEND_DATA` 组合 |

---

## 7. 运维手册

### 7.1 日常查看

```bash
# DeerFlow 状态/日志
sudo docker ps --filter name=deer-flow
sudo docker logs -f deer-flow-gateway

# MCP 状态/日志
sudo docker ps --filter name=deerflow-mcp
cd /data/deerflow-mcp && sudo docker compose logs -f mcp-seatunnel
```

### 7.2 重启/更新

```bash
# MCP 代码更新后
cd /data/deerflow-mcp
sudo docker compose up -d --build
sudo docker restart deer-flow-gateway        # 刷新工具缓存（必须）

# DeerFlow 整体
cd /data/deer-flow && sudo bash scripts/deploy.sh start|down
```

### 7.3 手工快速自检（不经过 DeerFlow）

```bash
# MCP 协议级：列出工具
docker exec deerflow-mcp-seatunnel python -c "
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
async def m():
    async with streamablehttp_client('http://localhost:9103/mcp') as (r,w,_):
        async with ClientSession(r,w) as s:
            await s.initialize()
            print([t.name for t in (await s.list_tools()).tools])
asyncio.run(m())"

# SeaTunnel REST 直查
curl http://10.131.102.145:8080/finished-jobs
```

### 7.4 对话测试提示词（已验证）

```
把 MySQL test 库的 tab01 表同步到 PostgreSQL，目标表叫 tab01_from_mysql
```

Agent 自动执行：describe MySQL 表 -> 生成作业配置（占位密码）-> 展示确认 -> submit_job -> 轮询状态 -> postgres read_query 校验行数。

---

## 8. 已知限制与后续方向

**限制：**
1. 重复同步同一张已存在目标表会撞 SeaTunnel PG catalog bug（规避：先 DROP，或换表名）
2. Doris BE 在该 VMware 虚拟机上因无 AVX2 指令无法启动，Doris 方向的 sink 暂不可用
3. `read_query` 结果截断 200 行，适合元数据/校验，不适合大数据量搬运（搬运本来就该走 SeaTunnel）
4. 模型偶发漏传工具参数会重试（观察即可，连续失败再看 gateway 日志）

**可扩展方向：**
- OpenMetadata MCP（元数据/血缘登记，REST :8585 现成）
- Dagster/dbt MCP（调度与批计算闭环，145 已部署）
- STREAMING 模式 CDC 同步（MySQL-CDC connector，需开 binlog）
- `mcpInterceptors` 加审计/白名单拦截器

---

## 9. 凭证汇总（内网测试环境）

| 服务 | 地址 | 账号/密码 |
|------|------|----------|
| DeerFlow UI | http://10.131.102.145:2026 | /setup 自建管理员 |
| MySQL | 10.131.102.145:3306 | root / CHANGE_ME_mysql |
| PostgreSQL | 10.131.102.145:5433 | omop / CHANGE_ME_pg_omop |
| SeaTunnel REST | http://10.131.102.145:8080 | 无认证 |
| MCP server | :9101 / :9102 / :9103 | 无认证（仅内网；密码在容器 env） |

---


---

# 附录（2026-08-18 第二批接入）：MinIO / OpenMetadata / Trino / Hive / Doris

## 新增架构

```
DeerFlow gateway
  ├─ minio-mcp         :9104 ──> MinIO S3         145:9000 (buckets: iceberg, lake)
  ├─ openmetadata-mcp  :9105 ──> OpenMetadata     144:8585 (admin/admin, JWT 登录)
  ├─ trino-mcp         :9106 ──> Trino            144:8080 (catalogs: iceberg, system)
  ├─ hive-mcp          :9107 ──> HiveServer2      144:30000 (dbs: default, omopdb, testdb)
  └─ doris-mcp         :9108 ──> Doris FE(MySQL)  145:9030 (root 空密码, db: omopdb)
```

共 8 个 MCP server、42 个工具，全部经 DeerFlow 自带客户端栈（gateway 容器内）验证可发现。

## 新增文件（/data/deerflow-mcp）

- `minio_mcp.py`：list_buckets / list_objects / read_text_object / put_text_object / delete_object / presigned_url（minio SDK）
- `openmetadata_mcp.py`：search_metadata / get_table_details / get_lineage / list_database_services / list_tables（REST + JWT，密码 base64 后登录换 token）
- `db_mcp.py` 扩展两个方言分支：
  - `DB_TYPE=trino`（trino dbapi，ALLOW_WRITE=false 只读；list_databases=SHOW CATALOGS，database 参数格式 catalog.schema）
  - `DB_TYPE=hive`（impyla，auth PLAIN，可由 HIVE_AUTH 切 NOSASL）
  - Doris 直接复用 mysql 分支（MySQL 协议 9030 端口，compose 新增 mcp-doris 服务）

## 本批踩坑

| 现象 | 根因 | 解决 |
|------|------|------|
| MinIO `Object of type datetime is not JSON serializable` | bucket 创建时间是 datetime | `json.dumps(..., default=str)` |
| OM 登录 400 `Password needs to be encoded in Base-64` | OM 1.13 要求密码 base64 编码后提交 | login 前编码 |
| OM `Failed to find index table_index` | 索引名应为 `table_search_index` 等 | index_map 映射 |
| OM `Invalid field name owner` | 该版本 services 接口不支持 fields=owner | 去掉该参数 |
| Doris 表查询可能失败 | BE 因虚拟机无 AVX2 未运行（老问题） | 工具描述已注明；FE 层 DDL/列表正常 |

## 测试结果（全部通过）

- MinIO：2 个 bucket（iceberg、lake）
- OpenMetadata：服务列表返回（含 hive-144）、全文检索正常
- Trino：SHOW CATALOGS 返回 iceberg/system；iceberg.information_schema 列出 8 张系统表
- Hive：3 个库（default、omopdb、testdb）
- Doris：FE 返回 omopdb

## 对话测试建议

```
1. 看 MinIO 的 iceberg 桶里有哪些对象
2. 在 OpenMetadata 里搜一下 hive 相关的表，看看 hive-144 服务下有什么
3. 用 Trino 查 iceberg catalog 里有哪些库和表
4. 查一下 Hive testdb 里有哪些表，表结构是什么
5. 把 Hive testdb 的表结构整理成一份 JSON 报告存到 MinIO lake 桶里
```

## 凭证补充

| 服务 | 地址 | 账号/密码 |
|------|------|----------|
| OpenMetadata (144) | http://10.131.102.144:8585 | admin@open-metadata.org / admin |
| Airflow ingestion (144) | http://10.131.102.144:8081 | admin / admin |
| MinIO | 145:9000(S3) / 9001(Console) | minioadmin / CHANGE_ME_minio |
| Trino (144) | http://10.131.102.144:8080 | admin（无认证） |
| Hive (144) | HS2 NodePort 30000 / Metastore 30083 | 无认证 |
| Doris FE (145) | :8030(Web) / :9030(MySQL) | root / 空密码 |

---

# 附录二：SeaTunnel 同步数据到 Hive 排查实录（2026-08-20）

## 最终结论

**MySQL -> Hive 同步已通过原生 Hive connector 打通并接入 DeerFlow（MCP 端到端验证通过）。**

可用的作业配置（JSON 模板，Hive 端必需项只有 `metastore_uri` 和 `table_name`）：

```json
{"env": {"job.mode": "BATCH", "parallelism": 1},
 "source": [{"plugin_name": "Jdbc",
   "url": "jdbc:mysql://10.131.102.145:3306/test",
   "driver": "com.mysql.cj.jdbc.Driver",
   "user": "root", "password": "...",
   "query": "SELECT id, name FROM tab01"}],
 "sink": [{"plugin_name": "Hive",
   "metastore_uri": "thrift://10.131.102.144:30083",
   "table_name": "testdb.tab01_hive_mcp"}]}
```

要点：
- `table_name` 必须是 `"库.表"` 格式；写成 `hive_database_name`/`hive_table_name`
  会报 `Unable to create a sink for identifier 'Hive'`（这正是之前误判为"插件未安装"的真凶）
- 目标 Hive 表需先用 hive MCP 的 `execute_sql` 建好（建议 `STORED AS TEXTFILE`）
- 重复同步是 append 语义；全量重灌需先 DROP/重建表
- 密码占位符注入规则与 PG/MySQL 一致

## 环境架构关键认知

- **145 本身就是 144 K8s 集群的工作节点（ubuntn145）**，flannel 路由使 145 上的
  Docker 容器（含 SeaTunnel）可以直接访问全部 pod IP（10.244.x.x）和 ClusterIP
  （kube-proxy DNAT）。**因此无需暴露任何 K8s 端口**。
- HDFS NameNode：`hadoop-master.hadoop.svc.cluster.local:8020`（ClusterIP
  10.102.146.73），NodePort 30820/30870 也已存在
- Hive warehouse 在 K8s 内部 HDFS：`hdfs://hadoop-master.hadoop.svc.cluster.local:8020/user/hive/warehouse`

## 走过的弯路（按时间线）

| # | 尝试 | 结果 | 原因 |
|---|------|------|------|
| 1 | `plugin_name: "Hive"` + `hive_database_name`/`hive_table_name` | "Unable to create a sink" | 配置键名错误，必需项是 `table_name`（被外层错误掩盖，看 docker logs 才见 `options('table_name') are required`） |
| 2 | Jdbc sink 走 `jdbc:hive2://` | "缺少 Hive JDBC 驱动" | 镜像 lib 里没有 hive-jdbc；下载 `hive-jdbc-3.1.3-standalone.jar` 放入 `/opt/seatunnel/lib` 解决连接 |
| 3 | 同上 | `NoSuchMethodError: HiveAuthUtils` | 镜像自带 hive-exec 里的同名类（非 shade 版）按 classpath 顺序抢先加载；移除镜像的 hive-exec/hive-service/libfb303 后连接成功 |
| 4 | 同上 | "The Hive jdbc connector don't support sink" | SeaTunnel 2.3.13 Hive JDBC 方言仅支持 source；加 `"compatible_mode": "inceptor"` 走 Inceptor 方言可绕过 |
| 5 | 同上 | `SQLFeatureNotSupportedException: addBatch` | **Hive JDBC 驱动（3.1.3 和 4.0.0 均是）从未实现 JDBC batch**，而 SeaTunnel JdbcSink 固定走批量路径。此路彻底不通 |
| 6 | 原生 Hive connector | `Permission denied: user=root, access=WRITE, inode="/tmp"` | SeaTunnel 以 root 连 HDFS；设 `HADOOP_USER_NAME=hadoop` 解决 |
| 7 | 原生 Hive connector | 主机名解析失败 | 容器 /etc/hosts 加 `hadoop-master.hadoop.svc.cluster.local -> 10.102.146.73` |

## 最终部署改动（145）

1. **medgov compose**（`/opt/ai-native-medical-data-governance-platform-docker/compute.yml` 的 seatunnel 服务，改前备份 compute.yml.bak-*）：
   ```yaml
   environment:
     JvmOption: -Xms1g -Xmx${SEATUNNEL_JVM_XMX:-2g}
     # 以 HDFS 属主身份写入（SeaTunnel 默认 root 无 HDFS /tmp 写权限）
     HADOOP_USER_NAME: hadoop
   # 145 本身是 K8s 节点，经 flannel 路由直连 HDFS NameNode（ClusterIP）
   extra_hosts:
     - "hadoop-master.hadoop.svc.cluster.local:10.102.146.73"
   ```
   然后 `docker compose ... --profile compute up -d seatunnel` 重建。
   注意：容器重建后 lib 恢复镜像原始状态（hive-exec 等原生 connector 依赖都在），
   废弃的 hive-jdbc-standalone 已从宿主机 `jars/seatunnel/lib/` 移除，不会再被
   启动脚本复制进去。镜像三个 hive jar 的备份保留在 `jars/seatunnel/lib-backup-image-hive/`。

2. **seatunnel MCP**（`/data/deerflow-mcp/seatunnel_mcp.py`）：submit_job 工具
   说明中加入 Hive 同步规则（第 8-12 条）与 MySQL -> Hive 模板，MCP 容器已重建。

## 遗留问题

- HiveServer2 上带 ORDER BY / COUNT 等触发 MR 的查询报
  `User: hadoop is not allowed to impersonate hadoop`（Hive 部署自身的代理用户
  配置问题，与同步无关；纯 SELECT * 不受影响）。如需 MR 查询，需在 144 的
  Hive 部署中配置 hadoop.proxyuser。
- Trino 的 iceberg catalog 指向 Nessie（http://nessie:19120），当前不可达，
  Iceberg 相关能力待 144 侧修复。

---

# 附录三：Dagster 接入 DeerFlow（2026-08-20）

## 结论

**Dagster 1.13.12 已通过 MCP 接入 DeerFlow，端到端验证通过**（经 MCP 触发
`materialize_assets` -> run SUCCESS，标签 `deerflow/note` 正确写入）。

## 部署信息

- Dagster webserver：`http://10.131.102.145:3000`（容器 medgov-dagster-webserver-1，
  GraphQL 端点 `/graphql`）；daemon 容器 medgov-dagster-daemon-1
- 代码位置：`medgov`，仓库名 `__repository__`，默认资产作业 `__ASSET_JOB`
- 资产：`m0_heartbeat`（M0 冒烟资产）

## MCP 服务

`/data/deerflow-mcp/dagster_mcp.py`，容器 `deerflow-mcp-dagster`，端口 9109，
compose 服务名 `mcp-dagster`。8 个工具：

| 工具 | 用途 |
|------|------|
| dagster_overview | 一次拿到代码位置/资产/最近运行全貌（对话入口） |
| list_assets | 列出资产 key 与描述 |
| list_runs | 最近运行记录 |
| get_run_details | 运行详情：状态、步骤、标签、物化统计 |
| materialize_assets | 物化指定资产（经 __ASSET_JOB + asset_selection 标签） |
| launch_job | 启动指定作业（可附 run_config_yaml） |
| terminate_run | 终止运行（含安全确认要求） |
| reload_workspace | 代码变更后重载代码位置 |

## Dagster 1.13 GraphQL 要点（调试时踩过的坑）

- `repositoryOrError` 需要 `repositorySelector` 参数，不能直接传
  locationName/repositoryName
- 运行列表用 `runsFeedOrError(limit: Int!, view: RUNS)`，view 是必填枚举
  （RUNS/ROOTS/BACKFILLS），结果要 `... on Run` 内联片段
- run 详情的 `stats` 需要 `... on RunStatsSnapshot` 片段；步骤字段是
  `stepKey` 不是 stepName
- 物化资产：`launchRun(executionParams: {selector: {..., jobName: "__ASSET_JOB"},
  executionMetadata: {tags: [{key: "dagster/asset_selection",
  value: "[\"资产名\"]"}]}})`（ExecutionParams 无 assetSelection 字段，
  选择范围靠这个 tag 传递）
- jobName 是 `__ASSET_JOB`（单下划线），写成 `__ASSET_JOB__` 报 PipelineNotFound

## DeerFlow 中的用法

新开对话即可，例如：
- "看一下 dagster 里有哪些资产和最近的运行"
- "物化 m0_heartbeat 资产，备注：数据同步完成后的例行检查"
- "查一下刚才那次运行的状态和步骤详情"

至此 DeerFlow 共接入 9 个 MCP：mysql、postgres、seatunnel、minio、
openmetadata、trino、hive、doris、dagster（共 50 个工具）。
