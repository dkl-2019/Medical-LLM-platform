# Docker 部署 SeaTunnel 避坑指南

## 环境信息

- 服务器：10.131.102.114
- 架构：ARM
- SeaTunnel 版本：apache/seatunnel:latest (2.3.12)
- 主目录：/opt/seatunnel
- Web 端口：8080
- 集群端口：5801

## 部署步骤

### 1. 拉取镜像

```bash
# 先确认镜像存在（已在服务器上）
docker images | grep seatunnel

# 如果需要拉取（注意ARM架构）
docker pull apache/seatunnel:latest
```

### 2. 准备配置文件

SeaTunnel 使用 Hazelcast 做集群通信，需要修改配置文件中的 member 地址：

```bash
# 修改 hazelcast.yaml
vi /opt/seatunnel/config/hazelcast.yaml
```

```yaml
hazelcast:
  cluster-name: seatunnel
  network:
    rest-api:
      enabled: true
      endpoint-groups:
        CLUSTER_WRITE:
          enabled: true
        DATA:
          enabled: true
    join:
      tcp-ip:
        enabled: true
        member-list:
          - 10.131.102.114
    port:
      auto-increment: false
      port: 5801
```

```bash
# 修改 hazelcast-client.yaml
vi /opt/seatunnel/config/hazelcast-client.yaml
```

```yaml
hazelcast-client:
  cluster-name: seatunnel
  properties:
    hazelcast.logging.type: log4j2
  connection-strategy:
    connection-retry:
      cluster-connect-timeout-millis: 3000
  network:
    cluster-members:
      - 10.131.102.114:5801
```

### 3. 启动容器

```bash
docker rm -f seatunnel
docker run -d \
  --name seatunnel \
  -p 8080:8080 \
  -p 5801:5801 \
  -v /opt/seatunnel:/opt/seatunnel \
  apache/seatunnel:latest \
  /opt/seatunnel/bin/seatunnel-cluster.sh -r master -cn seatunnel
```

### 4. 验证

```bash
# 检查容器状态
docker ps | grep seatunnel

# 访问 Web UI
curl http://localhost:8080
# 或
curl http://10.131.102.114:8080
```

---

## 避坑总结

### 坑1：镜像默认 CMD 是 bash，不是服务

- **问题**：`apache/seatunnel:latest` 镜像默认启动命令是 `bash`，容器启动后会立即退出
- **现象**：容器状态 `Exited (0)`
- **解决**：必须在启动命令中指定服务启动脚本

### 坑2：启动参数用 `-m cluster` 会失败

- **问题**：使用 `-m cluster -cn seatunnel` 启动会报 `Unable to connect to any cluster`
- **原因**：`-m cluster` 是客户端模式，需要连接已存在的集群
- **解决**：使用 `-r master` 启动 Master 节点

### 坑3：hazelcast.yaml 配置 localhost 连不上

- **问题**：配置 `member-list: - localhost` 在容器内连不上自己
- **解决**：改成服务器 IP `10.131.102.114`

### 坑4：端口被占用

- **问题**：8080 端口被 `datahub-gms` 等其他容器占用
- **解决**：
  1. 停掉占用端口的容器：`docker stop datahub-gms`
  2. 或给 SeaTunnel 换端口（如 8082）

### 坑5：Docker 无法拉取镜像

- **问题**：直连 docker.io 超时
- **解决**：
  1. 配置国内镜像源（但本环境测试未成功）
  2. **推荐**：在有网络的机器上先 `docker pull`，然后 `docker tag` / `docker save` / `scp` 到目标机器

### 坑6：挂载目录 /opt/seatunnel 必须是空的

- **问题**：如果 /opt/seatunnel 已存在且有内容，容器内的 /opt/seatunnel 不会显示镜像内的文件
- **解决**：挂载前先清空或删除目录，或先 `docker create` + `docker cp` 导出文件

---

## 正确启动命令

```bash
# 完整部署命令
docker rm -f seatunnel
rm -rf /opt/seatunnel
docker run -d \
  --name seatunnel \
  -p 8080:8080 \
  -p 5801:5801 \
  -v /opt/seatunnel:/opt/seatunnel \
  apache/seatunnel:latest \
  /opt/seatunnel/bin/seatunnel-cluster.sh -r master -cn seatunnel
```

---

## 访问地址

- Web UI：http://10.131.102.114:8080
- 集群通信：10.131.102.114:5801
