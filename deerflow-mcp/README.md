# DeerFlow MCP 服务器集

> 自研 MCP(Model Context Protocol)工具服务,让 DeerFlow 大模型 Agent 通过自然语言对话
> 操作数据栈:数据库查询、数据同步、对象存储、元数据治理、任务编排。
>
> 服务器部署:10.131.102.145 `/data/deerflow-mcp`(本目录与之同步)
> 开发记录:2026-08 至今 · 9 个 MCP 服务 · 50 个工具 · 端到端验证通过

---

## 1. 服务总览

| MCP 服务 | 端口 | 代码 | 目标组件 | 工具数 |
|---------|------|------|---------|-------|
| mysql | 9101 | db_mcp.py (DB_TYPE=mysql) | MySQL 8 · 145:3306(his_demo/test) | 5 |
| postgres | 9102 | db_mcp.py (DB_TYPE=pg) | PostgreSQL · 145:5433(omop) | 5 |
| seatunnel | 9103 | seatunnel_mcp.py | SeaTunnel Zeta 2.3.13 · 145:8080 | 6 |
| minio | 9104 | minio_mcp.py | MinIO · 145:9000(iceberg/lake 桶) | 6 |
| openmetadata | 9105 | openmetadata_mcp.py | OpenMetadata 1.13.1 · 144:8585 | 5 |
| trino | 9106 | db_mcp.py (DB_TYPE=trino) | Trino · 144:8080(**只读**) | 4 |
| hive | 9107 | db_mcp.py (DB_TYPE=hive) | HiveServer2 · 144:30000 | 5 |
| doris | 9108 | db_mcp.py (DB_TYPE=mysql) | Doris FE · 145:9030(MySQL 协议) | 5 |
| dagster | 9109 | dagster_mcp.py | Dagster 1.13.12 · 145:3000(GraphQL) | 8 |

```
用户对话
  └─ DeerFlow 2.0 (145:2026, extensions_config.json 注册)
       │  Agent 编排,streamable-http 调 MCP 工具
       ├─ mysql :9101 ─> MySQL      ├─ openmetadata :9105 ─> OM (144)
       ├─ postgres :9102 ─> PG      ├─ trino  :9106 ─> Trino (144)
       ├─ seatunnel :9103 ─> 同步   ├─ hive   :9107 ─> HiveServer2 (144)
       ├─ minio :9104 ─> S3         ├─ doris  :9108 ─> Doris FE
       └─ dagster :9109 ─> 编排调度
```

## 2. 代码结构

```
db_common.py          共享库:SQL 只读正则校验、结果截断(200 行)、JSON 序列化
db_mcp.py             通用 DB server:DB_TYPE 环境变量分派 mysql/pg/trino/hive 四方言
seatunnel_mcp.py      SeaTunnel Zeta REST 封装(密码占位符自动注入 + Hive 同步规则)
minio_mcp.py          MinIO S3 对象操作
openmetadata_mcp.py   元数据检索/表详情/血缘(REST + JWT,密码 base64 登录)
dagster_mcp.py        Dagster GraphQL:资产物化/作业启动/运行跟踪
requirements.txt      mcp>=1.2.0,<2.0.0(必须锁!)、httpx、pymysql、psycopg[binary] 等
Dockerfile            python:3.12-slim(离线环境走清华 pypi)
docker-compose.yml    9 个服务,端口 9101-9109
README.md             本文件
```

**技术选型**:Python `mcp` SDK 的 `FastMCP` + `streamable-http` 传输(常驻容器、路径 `/mcp`,
比 stdio 好部署好监控);DeerFlow 侧走 `langchain-mcp-adapters`,
`extensions_config.json` 填 `{"type": "http", "url": "http://10.131.102.145:91xx/mcp"}` 即接入。

## 3. 新增 MCP 工具/服务指南(后续开发看这里)

### 3.1 新增一个工具(改现有 py 文件)

1. 在对应 `*_mcp.py` 里加函数,docstring 用**中文**写清用途、参数、安全要求
   (工具描述会快照进模型上下文,是 Agent 正确使用的关键)
2. 传输部署(145):`cd /data/deerflow-mcp && docker compose up -d --build <service>`
3. `docker restart deer-flow-gateway` 刷新工具缓存(**必须**)
4. DeerFlow **新开对话**测试(工具描述按会话快照,旧会话看不到新工具)
5. 更新本 README 的服务总览表

### 3.2 新增一个 MCP 服务(完整清单)

1. 写 `xxx_mcp.py`,开头环境变量约定:`PORT`(默认分配下一个 9110+)+ 各连接参数
2. Dockerfile 的 COPY 行加上新文件;docker-compose.yml 加服务(参考 mcp-dagster)
3. 145 上同步代码后 `docker compose up -d --build <新服务>`
4. `/data/deer-flow/extensions_config.json` 加注册项(**原地写** `cat >`,不要 `sed -i`/`mv`
   ——单文件 bind mount 会因 inode 变化导致容器内看不到新内容)
5. `docker restart deer-flow-gateway`,新开对话验证工具发现
6. 更新本 README(服务总览表 + 架构图)

### 3.3 开发规范(踩坑沉淀,务必遵守)

- **注释/docstring 一律中文**,标识符英文
- **`mcp` 必须锁 `<2.0.0`**:2.0 移除了 `mcp.server.fastmcp` 模块路径,装上即崩
- **docstring 陷阱**:带 `.format()`/f-string 的 docstring 不是字符串字面量,
  `__doc__` 为空 → FastMCP 注册的工具没有描述,模型不会用。必须显式赋
  `fn.__doc__ = ...` 再 `mcp.tool()(fn)` 注册(见 db_mcp.py 中三处)
- **密码永远不进模型上下文**:作业配置里写 `...` 占位符,服务端按环境变量注入
  (seatunnel_mcp.py 的 `_inject_credentials`)
- **写操作工具描述必须包含确认要求**:execute_sql/stop_job/terminate_run 均要求
  Agent 先向用户展示并获确认

## 4. 安全设计

| 机制 | 实现位置 | 说明 |
|------|---------|------|
| 只读硬校验 | db_common.py + read_query | 正则强制单条 SELECT/WITH/SHOW/EXPLAIN/DESCRIBE,多语句拒绝 |
| 凭据隔离 | 容器 env + 密码注入 | 真实密码只在容器环境变量;模型只见占位符 |
| 写确认 | execute_sql 等工具描述 | Agent 必须先展示 SQL 并获用户确认 |
| 写开关 | ALLOW_WRITE env | trino 即以此设为只读 |
| 结果防爆 | db_common.py | 查询结果截断 200 行 |

## 5. 数据同步(SeaTunnel)——已验证链路与模板

### 5.1 REST API(2.3.13 实测,端口 8080)

| 端点 | 方法 | 说明 |
|------|------|------|
| `/submit-job?jobName=x` | POST | body=作业 JSON;Content-Type: application/json |
| `/running-jobs` `/finished-jobs` | GET | 作业列表(含 createTime/finishTime,东八区) |
| `/job-info/{jobId}` | GET | 详情/错误 |
| `/stop-job?jobId=x&isStopWithSavePoint=false` | POST | 停作业 |
| `/system-monitoring-information` | GET | 集群负载 |

注意:旧文档的 `/hazelcast/rest/maps/submit-job` 在 2.3.13 已 404。**不需要 CLI,REST 全搞定。**

### 5.2 MySQL → PostgreSQL 模板(自动建表,已验证)

```json
{"env": {"job.mode": "BATCH", "parallelism": 1},
 "source": [{"plugin_name": "Jdbc",
   "url": "jdbc:mysql://10.131.102.145:3306/test",
   "driver": "com.mysql.cj.jdbc.Driver",
   "user": "root", "password": "...",
   "query": "SELECT id, name, city FROM tab01"}],
 "sink": [{"plugin_name": "Jdbc",
   "url": "jdbc:postgresql://10.131.102.145:5433/omop",
   "driver": "org.postgresql.Driver",
   "user": "omop", "password": "...",
   "database": "omop", "table": "tab01_from_mysql",
   "primary_keys": ["id"], "generate_sink_sql": true,
   "schema_save_mode": "CREATE_SCHEMA_WHEN_NOT_EXIST",
   "data_save_mode": "APPEND_DATA"}]}
```

前置(一次性):目标库里 `CREATE SCHEMA IF NOT EXISTS omop;`
(PG sink 的 `database` 选项同时是 URL 库名和 SQL schema 前缀,必须同名)。

### 5.3 MySQL → Hive 模板(原生 connector,已验证)

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

要点:
- `table_name` 必须是 `"库.表"`;写成 `hive_database_name`/`hive_table_name` 会报
  `Unable to create a sink for identifier 'Hive'`(极易误判为"插件未安装")
- 目标 Hive 表需先建好(hive MCP execute_sql,建议 `STORED AS TEXTFILE`)
- **不要走 jdbc:hive2:// 的 Jdbc sink**:Hive JDBC 驱动从未实现 addBatch,此路不通
- 重复同步为 append 语义;全量重灌先 DROP 重建
- 服务端已配好 `HADOOP_USER_NAME=hadoop` + extra_hosts(见附录一)

### 5.4 submit_job 的三层防御

1. **格式自动纠正**:JSON 的 source/sink/transform 传对象(HOCON 风格)自动包成数组
2. **密码自动注入**:占位符(`...`/`***`/`$MYSQL_PASSWORD` 等)按同级 `url` 判断方言,
   用容器环境变量替换——**模型永远不知道真实密码**
3. **工具描述内置规则**:数组格式、PG schema 要求、Hive 同步规则(8-12 条)、
   重复同步先删表、提交前向用户展示配置确认

## 6. 踩坑记录(全部已解决或已规避)

### 6.1 MCP 框架层

| 现象 | 根因 | 解决 |
|------|------|------|
| 容器启动崩:`No module named 'mcp.server.fastmcp'` | pip 装了 mcp 2.0,模块路径变了 | requirements 锁 `mcp<2.0.0` |
| 工具在 DeerFlow 里没有描述、模型不会用 | `.format()`/f-string 的 docstring 不是字面量,`__doc__` 为空 | 显式赋 `fn.__doc__` 再 `mcp.tool()(fn)` |
| PG `syntax error at or near "$1"` | psycopg3 不支持 `NOT IN %s` 元组展开 | 改 `<> ALL(%s)` + list |
| DeerFlow 提交作业报参数缺失 | 参数名 `config` 太通用+模型偶发漏传 | 改名 `job_config` + 空参数返回明确错误 |
| 改了 extensions_config.json 容器里不生效 | sed -i/mv 换了 inode,单文件 bind mount 失联 | 原地写(`cat >`) |

### 6.2 SeaTunnel 同步

| 现象 | 根因 | 解决 |
|------|------|------|
| REST 提交报 `LinkedHashMap cannot be cast to ArrayList` | JSON 下 source/sink 必须是数组 | MCP server 自动包数组 |
| `relation "omop.xxx" does not exist` | PG sink 的 `database` 同时是库名和 schema 前缀 | 库里建同名 schema |
| `Failed creating table ... already exists` | 2.3.13 PG catalog bug(存在性检查与建表路径不一致) | 重复同步前先 DROP(已写进工具描述) |
| `Unable to create a source for identifier 'Jdbc'`(曾误判插件未装) | 外层包装错误,真实根因是密码错误(Access denied) | MCP 端密码注入 |
| Hive 同步 `Unable to create a sink for identifier 'Hive'` | 必需选项是 `table_name`("库.表"格式) | 见 5.3 模板 |
| Hive 同步 HDFS `Permission denied user=root` | SeaTunnel 以 root 连 HDFS | compose 加 `HADOOP_USER_NAME=hadoop` |
| Hive 同步主机名解析失败 | 容器不认识 K8s 内部域名 | extra_hosts 指向 NameNode ClusterIP |
| Create/Finish Time 与服务器差 8 小时 | JVM 默认 UTC | compose 加 `TZ=Asia/Shanghai` |
| 完成作业隔天消失 | `history-job-expire-minutes` 默认 1440(1 天) | 改 10080(保留 7 天),配置在 145 `config/seatunnel/seatunnel.yaml` |

### 6.3 各组件 API

| 现象 | 根因 | 解决 |
|------|------|------|
| MinIO `datetime is not JSON serializable` | bucket 创建时间是 datetime | `json.dumps(..., default=str)` |
| OM 登录 400 `Password needs to be encoded in Base-64` | OM 1.13 要求 base64 | login 前编码 |
| OM `Failed to find index table_index` | 索引名错误 | index_map 映射(table_search_index 等) |
| OM services 接口 `Invalid field name owner` | 该接口不支持 fields=owner | 去掉该参数 |
| Dagster `PipelineNotFound` | jobName 写成 `__ASSET_JOB__`(双下划线) | 用 `__ASSET_JOB` |
| Dagster 资产物化无从下手 | ExecutionParams 无 assetSelection 字段 | 靠 `dagster/asset_selection` 标签传递 |

## 7. 运维手册(在 145 上)

```bash
# 状态/日志
docker ps --filter name=deerflow-mcp
cd /data/deerflow-mcp && docker compose logs -f mcp-seatunnel

# MCP 代码更新后(三步,缺一不可)
cd /data/deerflow-mcp
docker compose up -d --build          # 重建容器
docker restart deer-flow-gateway      # 刷新工具缓存
# 然后新开对话测试(工具描述按会话快照)

# 手工自检(不经过 DeerFlow,直接列工具)
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

# SeaTunnel 直查
curl http://10.131.102.145:8080/finished-jobs
```

对话测试提示词(已验证):

```
把 MySQL test 库的 tab01 表同步到 PostgreSQL,目标表叫 tab01_from_mysql
```

Agent 自动执行:describe MySQL 表 → 生成作业配置(占位密码)→ 展示确认 →
submit_job → 轮询状态 → postgres read_query 校验行数。

## 8. 已知限制与后续方向

**限制:**
1. 重复同步同一张已存在 PG 目标表会撞 SeaTunnel catalog bug(规避:先 DROP)
2. Doris BE 在该 VMware 虚拟机上曾因无 AVX2 指令掉线(FE 的 DDL/列表不受影响)
3. `read_query` 截断 200 行,适合元数据/校验,不适合大数据量搬运(搬运走 SeaTunnel)
4. Hive MR 查询(ORDER BY/COUNT 触发)报 proxyuser 错误,纯 SELECT 不受影响
5. Trino iceberg catalog 指向 Nessie 不可达(144 侧待修)

**可扩展方向:**
- OpenMetadata MCP 增加血缘登记工具(add_lineage / delete_lineage / list_lineage_gaps),
  并在 seatunnel submit_job 成功后自动登记源→目标血缘(规划中)
- STREAMING 模式 CDC 同步(MySQL-CDC connector,需开 binlog)
- `mcpInterceptors` 加审计/白名单拦截器

---

## 附录一:SeaTunnel → Hive 排查实录(2026-08-20)

**结论:MySQL → Hive 经原生 Hive connector 打通,MCP 端到端验证通过。**

环境架构关键认知:
- **145 本身就是 144 K8s 集群的 worker 节点**,flannel 路由使 145 上的 Docker 容器
  可直访全部 pod IP(10.244.x.x)和 ClusterIP(kube-proxy DNAT),**无需暴露任何 K8s 端口**
- HDFS NameNode:`hadoop-master.hadoop.svc.cluster.local:8020`(ClusterIP 10.102.146.73)
- Hive warehouse:`hdfs://.../user/hive/warehouse`

走过的弯路(按时间线):

| # | 尝试 | 结果 | 原因 |
|---|------|------|------|
| 1 | `plugin_name: "Hive"` + 错误键名 | "Unable to create a sink" | 必需项是 `table_name`(被外层错误掩盖) |
| 2 | Jdbc sink 走 `jdbc:hive2://` | "缺少 Hive JDBC 驱动" | 镜像 lib 没有 hive-jdbc |
| 3 | 同上 | `NoSuchMethodError: HiveAuthUtils` | 镜像自带 hive-exec 同名类抢先加载 |
| 4 | 同上 | "don't support sink" | 2.3.13 Hive JDBC 方言仅支持 source |
| 5 | 同上+compatible_mode 绕过 | `addBatch` 不支持 | Hive JDBC 驱动从未实现 batch,**此路彻底不通** |
| 6 | 原生 connector | HDFS Permission denied(user=root) | 设 `HADOOP_USER_NAME=hadoop` 解决 |
| 7 | 原生 connector | 主机名解析失败 | extra_hosts 加 NameNode ClusterIP |

最终部署改动(medgov compose 的 seatunnel 服务):

```yaml
environment:
  JvmOption: -Xms1g -Xmx${SEATUNNEL_JVM_XMX:-2g}
  # 以 HDFS 属主身份写入(SeaTunnel 默认 root 无 HDFS /tmp 写权限)
  HADOOP_USER_NAME: hadoop
  # 作业时间显示用东八区(REST 的 Create/Finish Time 此前为 UTC,差 8 小时)
  TZ: Asia/Shanghai
# 145 本身是 K8s 节点,经 flannel 路由直连 HDFS NameNode(ClusterIP)
extra_hosts:
  - "hadoop-master.hadoop.svc.cluster.local:10.102.146.73"
```

## 附录二:Dagster 接入(2026-08-20)

**结论:Dagster 1.13.12 经 MCP 接入 DeerFlow,端到端验证通过**
(materialize_assets → run SUCCESS,`deerflow/note` 标签正确写入)。

- webserver:145:3000(GraphQL `/graphql`);daemon 同机部署
- 代码位置 `medgov`,仓库 `__repository__`,默认资产作业 `__ASSET_JOB`
- 8 个工具:dagster_overview / list_assets / list_runs / get_run_details /
  materialize_assets / launch_job / terminate_run / reload_workspace

Dagster 1.13 GraphQL 要点:
- `repositoryOrError` 需要 `repositorySelector` 参数
- 运行列表用 `runsFeedOrError(limit: Int!, view: RUNS)`,结果要 `... on Run` 内联片段
- run 详情 `stats` 需要 `... on RunStatsSnapshot` 片段;步骤字段是 `stepKey` 不是 stepName
- 物化资产:`launchRun(executionParams: {selector: {..., jobName: "__ASSET_JOB"},
  executionMetadata: {tags: [{key: "dagster/asset_selection", value: "[\"资产名\"]"}]}})`
- jobName 是 `__ASSET_JOB`(单下划线),写成 `__ASSET_JOB__` 报 PipelineNotFound

## 附录三:凭证(内网测试环境,真实值见 145 容器 env / 共享信息文档)

| 服务 | 地址 | 账号/密码 |
|------|------|----------|
| DeerFlow UI | http://10.131.102.145:2026 | admin@deerflow.com / adminADMIN |
| MySQL | 10.131.102.145:3306 | root / CHANGE_ME_mysql |
| PostgreSQL | 10.131.102.145:5433 | omop / CHANGE_ME_pg_omop |
| SeaTunnel REST | http://10.131.102.145:8080 | 无认证 |
| MinIO | 145:9000(S3) / 9001(Console) | minioadmin / CHANGE_ME_minio |
| OpenMetadata (144) | http://10.131.102.144:8585 | admin@open-metadata.org / admin |
| Airflow ingestion (144) | http://10.131.102.144:8081 | admin / admin |
| Trino (144) | http://10.131.102.144:8080 | admin(无认证) |
| Hive (144) | HS2 30000 / Metastore 30083 | 无认证 |
| Doris FE (145) | :8030(Web) / :9030(MySQL) | root / 空密码 |
