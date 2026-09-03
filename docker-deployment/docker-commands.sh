#!/bin/bash
# ============================================
# 114 服务器 Docker 部署命令
# 服务器 IP: 10.131.102.114
# Docker 数据目录: /var/lib/docker
# ============================================

# 创建必要目录
mkdir -p /data/seatunnel
mkdir -p /data/flink
mkdir -p /data/minio
mkdir -p /data/mysql
mkdir -p /data/doris/fe
mkdir -p /data/doris/be

# ============================================
# 1. MySQL (基础数据库)
# ============================================
docker run -d \
  --name mysql \
  --restart=always \
  -p 3306:3306 \
  -v /data/mysql:/var/lib/mysql \
  -e MYSQL_ROOT_PASSWORD=123456 \
  -e MYSQL_DATABASE=datahub \
  -e MYSQL_USER=datahub \
  -e MYSQL_PASSWORD=datahub \
  mysql:8.0

# 验证: mysql -h 10.131.102.114 -u root -p123456

# ============================================
# 2. MinIO (对象存储)
# ============================================
docker run -d \
  --name minio \
  --restart=always \
  -p 9000:9000 \
  -p 9001:9001 \
  -v /data/minio:/data \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin123 \
  minio/minio server /data --console-address ":9001"

# 访问: http://10.131.102.114:9001
# 账号: minioadmin
# 密码: minioadmin123

# ============================================
# 3. Apache Flink (流处理平台)
# ============================================
docker run -d \
  --name flink-jobmanager \
  --restart=always \
  -p 8081:8081 \
  -p 6123:6123 \
  -p 9002:9002 \
  -v /data/flink:/opt/flink \
  flink:1.17 jobmanager

# 启动 TaskManager
docker run -d \
  --name flink-taskmanager \
  --restart=always \
  --link flink-jobmanager \
  flink:1.17 taskmanager

# 访问: http://10.131.102.114:8081

# ============================================
# 4. Apache SeaTunnel (数据集成平台)
# ============================================
docker run -d \
  --name seatunnel \
  --restart=always \
  -p 5801:5801 \
  -p 8080:8080 \
  -v /data/seatunnel:/opt/seatunnel \
  -v /data/seatunnel/config:/opt/seatunnel/config \
  apache/seatunnel:2.3.12 \
  /opt/seatunnel/bin/seatunnel-cluster.sh -d

# 访问: http://10.131.102.114:8080

# ============================================
# 5. Apache Doris (OLAP 数据库)
# ============================================
# FE 节点
docker run -d \
  --name doris-fe \
  --restart=always \
  -p 8030:8030 \
  -p 9030:9030 \
  -p 9010:9010 \
  -v /data/doris/fe:/opt/apache-doris/fe \
  apache/doris:fe-4.0.4

# BE 节点
docker run -d \
  --name doris-be \
  --restart=always \
  -p 8040:8040 \
  -p 9050:9050 \
  -p 9060:9060 \
  -v /data/doris/be:/opt/apache-doris/be \
  --link doris-fe \
  apache/doris:be-4.0.4

# 访问: http://10.131.102.114:8030
# SQL: mysql -h 10.131.102.114 -P 9030 -u root

# ============================================
# 6. DataHub Frontend
# ============================================
docker run -d \
  --name datahub-frontend \
  --restart=always \
  -p 9002:9002 \
  acryldata/datahub-frontend:latest

# 访问: http://10.131.102.114:9002

# ============================================
# 7. Rainbond (云原生应用管理平台)
# ============================================
# 单节点安装
docker run -d \
  --name rainbond \
  --restart=always \
  -p 7070:7070 \
  -p 8888:8888 \
  -p 10254:10254 \
  -v /opt/rainbond/data:/grdata \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /opt/rainbond/etc:/opt/rainbond/etc \
  rainbond/rainbond:v6.0.0-amd64 \
  --init

# 访问: http://10.131.102.114:7070

# ============================================
# 常用运维命令
# ============================================
# 查看所有容器状态
docker ps -a | grep -E "mysql|minio|flink|seatunnel|doris|datahub|rainbond"

# 查看容器日志
docker logs -f <container-name>

# 停止所有容器
# docker stop mysql minio flink-jobmanager flink-taskmanager seatunnel doris-fe doris-be datahub-frontend rainbond

# 删除所有容器
# docker rm -f mysql minio flink-jobmanager flink-taskmanager seatunnel doris-fe doris-be datahub-frontend rainbond

# 批量重启
# docker restart mysql minio flink-jobmanager flink-taskmanager seatunnel doris-fe doris-be datahub-frontend rainbond
