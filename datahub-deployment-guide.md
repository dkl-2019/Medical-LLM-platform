# DataHub 部署与问题排查总结

## 一、DataHub 组件架构

DataHub 采用微服务架构，核心组件如下：

| 组件 | 镜像 | 端口 | 用途 |
|------|------|------|------|
| **DataHub GMS** | `acryldata/datahub-gms:v1.3.0.1` | 8082 | 图元数据服务（核心后端） |
| **DataHub Frontend** | `linkedin/datahub-frontend-react:db33c864` | 9002 | Web UI 前端 |
| **MySQL** | `mysql:8.0.46-oraclelinux9` | 3306 | 元数据持久化存储 |
| **Elasticsearch** | `docker.elastic.co/elasticsearch/elasticsearch:7.9.3` | 9202 | 搜索与索引 |
| **Neo4j** | `neo4j:latest` | 7474/7687 | 图数据库（血缘关系） |
| **Kafka** | `confluentinc/cp-kafka:7.5.0` | 9092 | 消息总线 |
| **Zookeeper** | `confluentinc/cp-zookeeper:7.5.0` | 2181 | Kafka 协调服务 |
| **DataHub Upgrade** | `acryldata/datahub-upgrade:v1.3.0.1` | - | 系统初始化/升级工具 |

## 二、部署流程

### 1. MySQL
```bash
docker run -d --name mysql \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=datahub \
  -e MYSQL_DATABASE=datahub \
  -e MYSQL_USER=datahub \
  -e MYSQL_PASSWORD=datahub \
  mysql:8.0.46-oraclelinux9
```

### 2. Elasticsearch
```bash
docker run -d --name elasticsearch \
  -p 9202:9200 \
  -e "discovery.type=single-node" \
  -e "xpack.security.enabled=false" \
  docker.elastic.co/elasticsearch/elasticsearch:7.9.3
```

### 3. Neo4j
```bash
docker run -d --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=none \
  neo4j:latest
```

### 4. Zookeeper
```bash
docker run -d --name zookeeper --network host \
  -e ZOOKEEPER_CLIENT_PORT=2181 \
  -e ZOOKEEPER_TICK_TIME=2000 \
  confluentinc/cp-zookeeper:7.5.0
```

### 5. Kafka（与 DataHub 1.3.0 兼容版本）
```bash
docker run -d --name kafka --network host \
  -e KAFKA_ZOOKEEPER_CONNECT=localhost:2181 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092 \
  -e KAFKA_LISTENERS=PLAINTEXT://0.0.0.0:9092 \
  -e KAFKA_BROKER_ID=1 \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR=1 \
  confluentinc/cp-kafka:7.5.0
```

### 6. DataHub GMS
```bash
# 先获取 entity-registry.yml
mkdir -p /tmp/metadata-models/src/main/resources/
docker run --rm acryldata/datahub-gms:v1.3.0.1 cat /metadata-models/src/main/resources/entity-registry.yml \
  > /tmp/metadata-models/src/main/resources/entity-registry.yml

# 启动 GMS
docker run -d --name datahub-gms --network host \
  -e SERVER_PORT=8082 \
  -e SPRING_DATASOURCE_URL="jdbc:mysql://localhost:3306/datahub?useUnicode=true&characterEncoding=UTF-8&useSSL=false" \
  -e SPRING_DATASOURCE_USERNAME=root \
  -e SPRING_DATASOURCE_PASSWORD=datahub \
  -e EBEAN_DATASOURCE_HOST=localhost:3306 \
  -e ELASTICSEARCH_HOST=localhost \
  -e ELASTICSEARCH_PORT=9202 \
  -e NEO4J_HOST=localhost:7474 \
  -e NEO4J_URI=bolt://localhost:7687 \
  -e KAFKA_BOOTSTRAP_SERVER=localhost:9092 \
  -e DATAHUB_SECRET=YouWillNeverGuessIt123 \
  -e MAE_CONSUMER_ENABLED=false \
  -e MCE_CONSUMER_ENABLED=false \
  -e PE_CONSUMER_ENABLED=false \
  -e UI_INGESTION_ENABLED=false \
  -e DATAHUB_ANALYTICS_ENABLED=false \
  -v /tmp/metadata-models/src/main/resources/entity-registry.yml:/metadata-models/src/main/resources/entity-registry.yml \
  acryldata/datahub-gms:v1.3.0.1
```

### 7. DataHub Frontend
```bash
docker run -d --name datahub-frontend -p 9002:9002 \
  -e DATAHUB_GMS_HOST=10.131.102.114 \
  -e DATAHUB_GMS_PORT=8082 \
  -e DATAHUB_SECRET=YouWillNeverGuessIt123 \
  -e KAFKA_BOOTSTRAP_SERVER=localhost:9092 \
  linkedin/datahub-frontend-react:db33c864
```

### 8. DataHub 系统初始化（SystemUpdate）
```bash
docker run --rm --network host \
  -v /tmp/metadata-models/src/main/resources/entity-registry.yml:/metadata-models/src/main/resources/entity-registry.yml \
  -e EBEAN_DATASOURCE_HOST=localhost:3306 \
  -e EBEAN_DATASOURCE_URL="jdbc:mysql://localhost:3306/datahub?useUnicode=true&characterEncoding=UTF-8&useSSL=false&allowPublicKeyRetrieval=true" \
  -e EBEAN_DATASOURCE_USERNAME=root \
  -e EBEAN_DATASOURCE_PASSWORD=datahub \
  -e KAFKA_BOOTSTRAP_SERVER=localhost:9092 \
  -e ELASTICSEARCH_HOST=localhost \
  -e ELASTICSEARCH_PORT=9202 \
  -e NEO4J_HOST=localhost:7474 \
  -e NEO4J_URI=bolt://localhost:7687 \
  -e DATAHUB_SECRET=YouWillNeverGuessIt123 \
  -e DATAHUB_ANALYTICS_ENABLED=false \
  -e DATAHUB_TELEMETRY_ENABLED=false \
  acryldata/datahub-upgrade:v1.3.0.1 \
  -u SystemUpdate
```

## 三、遇到的问题及解决方案

### 问题 1：DataHub GMS 连不上 MySQL
**现象：** `Connection refused to localhost:3306`
**原因：** GMS 容器在 bridge 网络下，`localhost` 指向容器自身，而非宿主机 MySQL。
**解决：** 将 GMS 改为 `--network host` 模式，使容器 `localhost` 与宿主机共享。

### 问题 2：entity-registry.yml 缺失
**现象：** GMS 启动报错 `../../metadata-models/src/main/resources/entity-registry.yml (No such file or directory)`
**原因：** 镜像中该文件路径缺失。
**解决：** 从 GMS 容器中复制文件到宿主机，再通过 `-v` 挂载到容器内对应路径。

### 问题 3：DataHub 前端登录失败
**现象：** 页面显示 "Failed to log in! An unexpected error occurred."
**原因：**
1. 前端容器配置的 `DATAHUB_GMS_HOST=datahub-gms` 无法 DNS 解析
2. GMS 端口配置错误（8080 而非实际 8082）
**解决：**
1. 删除旧前端容器，重新启动并指定 `-e DATAHUB_GMS_HOST=10.131.102.114 -e DATAHUB_GMS_PORT=8082`
2. 补齐 `-e KAFKA_BOOTSTRAP_SERVER=localhost:9092` 环境变量

### 问题 4：Kafka 版本不兼容（核心问题）
**现象：**
- 使用 `apache/kafka:4.2.1-rc4`（Kafka 4.x KRaft 模式）
- DataHub upgrade 容器卡在 Kafka admin client rebootstrap，无法创建 topic
- SystemUpdate 无法完成，数据库始终为空
**原因：** DataHub 1.3.0 发布于 2024 年，只兼容 Kafka 3.x 系列，不支持 Kafka 4.x 的 KRaft 模式。
**解决：** 替换为 `confluentinc/cp-kafka:7.5.0`（对应 Kafka 3.5.x）+ `confluentinc/cp-zookeeper:7.5.0`。

### 问题 5：MySQL 8.0 公钥检索问题
**现象：** `Public Key Retrieval is not allowed`
**原因：** MySQL 8.0 默认使用 `caching_sha2_password` 认证插件。
**解决：** 在 JDBC URL 中追加 `allowPublicKeyRetrieval=true`。

### 问题 6：datahub-upgrade 镜像版本不匹配
**现象：**
- 使用 `acryldata/datahub-upgrade:4ea04a6`，传入 `SQL_SETUP_ENABLED=true` 无效
- 日志始终显示 `SQL_SETUP_ENABLED=false`
**原因：** 该镜像 digest 对应的版本与 GMS v1.3.0.1 不匹配，存在环境变量识别 bug。
**解决：** 更换为与 GMS 同版本的 `acryldata/datahub-upgrade:v1.3.0.1`。

### 问题 7：数据库为空导致登录 401
**现象：** GMS `/logIn` 返回 401 Unauthorized
**原因：** DataHub 的 `datahub` 数据库中没有任何表，`metadata_aspect_v2` 表缺失，无法查询用户凭证。
**解决：** 运行 `datahub-upgrade:v1.3.0.1` 的 `SystemUpdate` 完成数据库 migration（**待完成**）。

## 四、当前状态

| 组件 | 状态 | 说明 |
|------|------|------|
| MySQL | Running | 端口 3306，root 密码 datahub |
| Elasticsearch | Running | 端口 9202 |
| Neo4j | Running | 端口 7474/7687 |
| Kafka | Running | Confluent 7.5.0，端口 9092 |
| Zookeeper | Running | 端口 2181 |
| DataHub GMS | Running (unhealthy) | 端口 8082，Kafka 已通，待数据库初始化 |
| DataHub Frontend | Running (healthy) | 端口 9002，已正确指向 GMS |
| DataHub Upgrade | 待执行 | 需运行 SystemUpdate 初始化数据库 |

## 五、待办事项

1. **运行 DataHub SystemUpdate** — 使用匹配版本的 upgrade 镜像完成数据库 migration
2. **验证登录** — 使用默认账号 `datahub` / `datahub` 登录前端
3. **验证 GMS health** — 确认 `/health` 返回 200
