# DeerFlow MCP 服务 Docker 部署手册

> 本目录保存 DeerFlow 已接入的全部 MCP 服务的 Docker 构建与编排信息,
> 与 145 服务器 `/data/deerflow-mcp` 目录内容保持同步(副本)。
>
> 12 个 MCP 服务 · 72 个工具 · 端口 9101-9112 · 最近更新:2026-09-10

---

## 1. 部署模型:一个镜像,十二个容器

所有 MCP 服务**共用同一个 Docker 镜像**,由 `docker-compose.yml` 通过不同的
`command`(入口 python 脚本)+ `environment`(端口、目标组件地址、凭证)
派生成 12 个独立容器:

```
镜像 deerflow-mcp-mcp (python:3.12-slim + requirements.txt)
  ├─ container: deerflow-mcp-mysql        command: python db_mcp.py         PORT=9101  DB_TYPE=mysql
  ├─ container: deerflow-mcp-pg           command: python db_mcp.py         PORT=9102  DB_TYPE=pg
  ├─ container: deerflow-mcp-seatunnel    command: python seatunnel_mcp.py  PORT=9103
  ├─ container: deerflow-mcp-minio        command: python minio_mcp.py      PORT=9104
  ├─ container: deerflow-mcp-openmetadata command: python openmetadata_mcp.py PORT=9105
  ├─ container: deerflow-mcp-trino        command: python db_mcp.py         PORT=9106  DB_TYPE=trino
  ├─ container: deerflow-mcp-hive         command: python db_mcp.py         PORT=9107  DB_TYPE=hive
  ├─ container: deerflow-mcp-doris        command: python db_mcp.py         PORT=9108  DB_TYPE=mysql(走 9030)
  ├─ container: deerflow-mcp-dagster      command: python dagster_mcp.py    PORT=9109
  ├─ container: deerflow-mcp-spark        command: python spark_mcp.py      PORT=9110
  ├─ container: deerflow-mcp-flink        command: python flink_mcp.py      PORT=9111
  └─ container: deerflow-mcp-hadoop       command: python hadoop_mcp.py     PORT=9112
```

**为什么不拆 12 个镜像?** MCP 服务代码高度同构(都是 FastMCP + httpx 封装 REST/JDBC),
共享镜像只需装一次依赖、改代码统一重建,运维成本低;隔离性靠"一容器一服务一端口"保证。

## 2. 本目录文件说明

| 文件 | 作用 |
|------|------|
| `Dockerfile` | 镜像定义:python:3.12-slim,清华 pypi 源(离线内网),COPY 全部 `*_mcp.py` 源码,EXPOSE 9101-9112 |
| `docker-compose.yml` | 12 个服务定义:容器名、command、环境变量(目标组件地址/凭证)、端口映射、restart 策略 |
| `requirements.txt` | Python 依赖。**关键锁定:`mcp>=1.2.0,<2.0.0`**(2.0 移除模块路径,升级会全挂) |

注意:`Dockerfile` 里 COPY 的是 `*_mcp.py` 源码文件,这些文件在
`../deerflow-mcp/` 目录(本目录只保存 Docker 编排信息)。**构建前需把
`deerflow-mcp/` 下的全部 py 文件放在 compose 文件同级目录**(145 上的
`/data/deerflow-mcp` 即如此)。

## 3. 容器构建流程(新增/修改 MCP 服务时)

### 3.1 修改了已有服务代码(如 seatunnel_mcp.py)

```bash
# 145 上,目录为 root 属主,需 sudo
cd /data/deerflow-mcp
sudo docker compose build mcp-seatunnel      # 重新构建镜像层(COPY 层变了)
sudo docker compose up -d mcp-seatunnel      # 重建容器
```

### 3.2 新增一个 MCP 服务(完整步骤)

1. **写代码**:在 `deerflow-mcp/` 新建 `xxx_mcp.py`(FastMCP + streamable-http,
   监听 `PORT` 环境变量,中文 docstring,工具描述必须是字面量)
2. **改 Dockerfile**:COPY 列表加上 `xxx_mcp.py`,EXPOSE 加上新端口
3. **改 docker-compose.yml**:按模板加服务块(见下)
4. **同步到 145**:`scp` 到 `/tmp` 再 `sudo cp` 进 `/data/deerflow-mcp`(目录 root 属主,
   直接 scp 会 Permission denied)
5. **构建启动**:`sudo docker compose up -d --build mcp-xxx`
6. **MCP 协议自检**(initialize → tools/list → tools/call 实调,见第 5 节)
7. **注册到 DeerFlow**:改 `/data/deer-flow/extensions_config.json`(见第 6 节)
8. **重启 gateway**:`sudo docker restart deer-flow-gateway`
9. **本地 Mac 同步 + git push**

新服务 compose 模板(以 hadoop 为例):

```yaml
  mcp-hadoop:
    build: .
    container_name: deerflow-mcp-hadoop
    command: ["python", "hadoop_mcp.py"]
    environment:
      PORT: "9112"
      HADOOP_NN_URL: http://10.131.102.144:30870
      YARN_RM_URL: http://10.131.102.144:30888
    ports:
      - "9112:9112"
    restart: unless-stopped
```

### 3.3 镜像分层说明

```
FROM python:3.12-slim
  ├─ 层1: ENV PIP_INDEX_URL=清华源(离线内网必须)
  ├─ 层2: COPY requirements.txt + pip install   ← 依赖不变则命中缓存,秒过
  └─ 层3: COPY *_mcp.py                          ← 改任何 py 都重建此层
```

日常改代码只动层3,构建很快;升级依赖才动层2。

## 4. 服务 ↔ 环境变量 ↔ 目标组件对照表

| compose 服务 | 端口 | 关键环境变量 | 目标组件 |
|-------------|------|-------------|---------|
| mcp-mysql | 9101 | DB_TYPE=mysql, DB_HOST/PORT/USER/PASSWORD | MySQL 145:3306 |
| mcp-pg | 9102 | DB_TYPE=pg, DB_HOST/PORT/USER/PASSWORD, DB_NAME=omop | PostgreSQL 145:5433 |
| mcp-seatunnel | 9103 | SEATUNNEL_URL, MYSQL_PASSWORD, PG_PASSWORD(占位符注入用) | SeaTunnel 145:8080 |
| mcp-minio | 9104 | MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY | MinIO 145:9000 |
| mcp-openmetadata | 9105 | OM_URL/USERNAME/PASSWORD(登录后缓存 JWT) | OpenMetadata 144:8585 |
| mcp-trino | 9106 | DB_TYPE=trino, TRINO_HOST/PORT/USER, ALLOW_WRITE=false | Trino 144:8080 |
| mcp-hive | 9107 | DB_TYPE=hive, HIVE_HOST/PORT/AUTH/USER | HiveServer2 144:30000 |
| mcp-doris | 9108 | DB_TYPE=mysql, DB_HOST=145, DB_PORT=9030 | Doris FE(MySQL 协议) |
| mcp-dagster | 9109 | DAGSTER_URL(graphql), DAGSTER_LOCATION=medgov | Dagster 145:3000 |
| mcp-spark | 9110 | SPARK_MASTER_URL | Spark Master REST 144:32080 |
| mcp-flink | 9111 | FLINK_REST_URL | Flink JobManager 144:32181 |
| mcp-hadoop | 9112 | HADOOP_NN_URL(JMX+WebHDFS), YARN_RM_URL | NameNode :30870 / RM :30888 |

> 凭据原则:真实密码只存在于容器环境变量(compose 里为 CHANGE_ME 占位,
> 145 上是真实值);代码与 Git 仓库不落真实密钥。

## 5. MCP 协议自检(部署后必做)

```bash
# 1. 初始化握手,拿 session id
curl -s -X POST http://10.131.102.145:9112/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "protocolVersion":"2024-11-05","capabilities":{},
    "clientInfo":{"name":"test","version":"1.0"}}}' -D /tmp/h -o /dev/null
SID=$(grep -i mcp-session-id /tmp/h | awk '{print $2}' | tr -d '\r')

# 2. 发 initialized 通知
curl -s -X POST http://10.131.102.145:9112/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' -o /dev/null

# 3. 列工具(应返回全部工具名)
curl -s -X POST http://10.131.102.145:9112/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# 4. 实调一个工具(method=tools/call, name=工具名, arguments={...})
```

要点:传输是 **streamable-http**,必须带 `Accept: application/json, text/event-stream`
头,且每次请求携带 `mcp-session-id`;响应是 SSE 格式,取 `data:` 行。

## 6. 注册到 DeerFlow(extensions_config.json)

MCP 容器跑起来后,DeerFlow 并不会自动发现,需在
`/data/deer-flow/extensions_config.json` 的 `mcpServers`(dict 结构)里登记:

```json
{
  "mcpServers": {
    "hadoop": {
      "enabled": true,
      "type": "http",
      "url": "http://10.131.102.145:9112/mcp",
      "description": "Hadoop 3.3.6 集群监控(只读)。工具: hadoop_overview/hdfs_status/..."
    }
  }
}
```

**两条铁律:**

1. **必须原地编辑**(sudo python 改写 / `sudo bash -c "cat > ..."`),
   不能 `sed -i`/`mv`——该文件是 bind mount,sed -i 换 inode 会导致容器内看不到变化
2. description 是给 Agent 看的工具索引,写清楚组件版本、地址、工具名和用法约定

改完只需 `sudo docker restart deer-flow-gateway`(config 是挂载卷,restart 即生效;
**.env 改动才需要 `scripts/deploy.sh start` 重建容器**)。
工具描述按会话快照,**新开会话**才能看到新工具。

## 7. 日常运维命令速查(145)

```bash
# 查看全部 MCP 容器状态/端口
sudo docker ps --format '{{.Names}}\t{{.Ports}}' | grep deerflow-mcp

# 看某容器日志
sudo docker logs --tail 50 deerflow-mcp-hadoop

# 重启单个服务(代码没改,只是重启)
sudo docker compose -f /data/deerflow-mcp/docker-compose.yml restart mcp-spark

# 改代码后重建单个服务
cd /data/deerflow-mcp && sudo docker compose build mcp-flink && sudo docker compose up -d mcp-flink

# 全部重建(改了 Dockerfile/requirements)
cd /data/deerflow-mcp && sudo docker compose up -d --build

# 验证 DeerFlow 网关健康
curl -s -o /dev/null -w "%{http_code}\n" http://10.131.102.145:2026/   # 200 即正常
```

## 8. 踩坑记录(Docker 相关)

| 坑 | 说明/解法 |
|----|----------|
| `mcp` SDK 升到 2.x 全部服务挂 | 2.0 移除模块路径,requirements 锁 `mcp>=1.2.0,<2.0.0` |
| docstring 用了 f-string/.format 工具描述为空 | `__doc__` 非字面量导致;显式 `fn.__doc__ = ...` 再注册 |
| `/data/deerflow-mcp` root 属主 | scp 到 `/tmp` 中转再 `sudo cp`;docker 命令都要 sudo |
| 离线内网 pip 拉不动 | Dockerfile 里 `PIP_INDEX_URL=清华源` |
| gateway 改了 extensions_config.json 不生效 | bind mount 必须**原地**改;restart 即可,不要重建容器 |
| gateway 改了 .env 不生效 | `docker restart` 不重载 env_file,必须 `cd /data/deer-flow && sudo bash scripts/deploy.sh start` 重建(直接 `docker compose up` 会缺 DEER_FLOW_HOME 等插值变量报 empty section between colons) |
| 容器内访问 144 K8s 组件 | 145 是 144 集群 worker,Pod/ClusterIP 直达;NodePort(30870/30888/32080/32181)走节点 IP |

## 9. 与其他目录的关系

```
Medical-LLM-platform/
├── deerflow-mcp/          ← MCP 源码(*_mcp.py)+ 开发文档(README 含工具/踩坑)
├── deerflow-mcp-docker/   ← 本目录:Docker 编排信息(Dockerfile/compose/requirements)
├── deer-flow/             ← DeerFlow 源码(含 config.yaml/.env 副本)
└── k8s-info/              ← 144 K8s 集群部署清单(Hadoop/Hive/Spark/Flink)
```

开发新 MCP 时:`deerflow-mcp/` 加代码 + 改本目录 Dockerfile/compose →
同步 145 → 构建验证 → 注册 DeerFlow → 更新两处 README → git push。
