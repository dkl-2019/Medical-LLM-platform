# K8s 环境信息总览

> 更新时间：2026-09-04

## 集群节点

| 节点名 | IP | 角色 | 配置 |
|--------|-----|------|------|
| ubuntn144 | 10.131.102.144 | control-plane | 32G 内存 / 1T 磁盘（/data） |
| ubuntn145 | 10.131.102.145 | worker | 64G 内存 / 1T 磁盘 |

- K8s 版本：v1.28.2（kubeadm 部署），CNI：Flannel（10.244.0.0/16）
- Dashboard：https://10.131.102.144:32129 （kube-system 命名空间，需 token 登录）
- 两节点已互相 SSH 免密（用户 user）

## 目录说明

```
k8s-info/                        # 全部 yaml 平铺，无二级目录
├── README.md                    # 本文件：环境总览
├── spark-k8s.yaml               # Spark 3.5.4 Standalone 集群部署清单
├── flink-k8s.yaml               # Flink 1.20 Session 集群部署清单
├── hadoop-k8s.yaml              # Hadoop master StatefulSet + worker Deployment + Service
├── hadoop-storage.yaml          # Hadoop StorageClass + 3 个静态 PV
├── hadoop-master-pvc.yaml       # Hadoop master PVC（volumeName 手动绑定 PV）
├── hadoop-master-sts.yaml       # Hadoop master StatefulSet（引用已绑定 PVC）
└── hive-k8s.yaml                # Hive 3.1.3（metastore + HiveServer2）
```

## 已部署服务与访问入口

### Hadoop 3.3.6（namespace: hadoop）

| 组件 | 位置 | 地址 |
|------|------|------|
| NameNode Web UI | 144 | http://10.131.102.144:30870 |
| YARN Web UI | 144 | http://10.131.102.144:30888 |
| HDFS RPC | 144 | hdfs://10.131.102.144:30820 |
| master Pod | ubuntn144（PVC 持久化 20Gi） | hadoop-master-0 |
| worker Pod | ubuntn145 + ubuntn144 各一个 | hadoop-worker-0/1（各 20Gi PVC） |

宿主机客户端：144/145 均已安装 /opt/hadoop（hdfs/yarn 命令可用，环境变量在 /etc/profile.d/hadoop.sh）。

### Hive 3.1.3（namespace: hive）

| 组件 | 地址 |
|------|------|
| HiveServer2 (JDBC) | jdbc:hive2://10.131.102.144:30000（用户 root，无密码） |
| Metastore | thrift://10.131.102.144:30083 |
| HiveServer2 Web UI | http://10.131.102.144:30002 |

- metastore 后端 MySQL：10.131.102.144:3306（openmetadata-mysql 容器）的 hive_metastore 库，root / openmetadata_password
- 宿主机客户端：144 已安装 /opt/hive（beeline 可用；hive CLI 需要 Java 8/11，系统 Java 21 下不可用）

### Spark 3.5.4（namespace: spark）— 本次部署

| 组件 | 位置 | 地址 |
|------|------|------|
| Master Web UI | ubuntn144 | http://10.131.102.144:32080 |
| Master RPC | — | spark://spark-master.spark.svc.cluster.local:7077（集群内） |
| Worker | ubuntn144（2C/4G） | spark-worker-144 |
| Worker | ubuntn145（4C/8G） | spark-worker-145 |

### Flink 1.20（namespace: flink）— 本次部署

| 组件 | 位置 | 地址 |
|------|------|------|
| JobManager Web UI / REST | ubuntn144 | http://10.131.102.144:32181 |
| JobManager RPC | — | flink-jobmanager.flink.svc.cluster.local:6123（集群内） |
| TaskManager | ubuntn144（2C/4G） | flink-taskmanager-144 |
| TaskManager | ubuntn145（4C/8G） | flink-taskmanager-145 |

## 镜像与代理

- 镜像通过 Mac（ClashX，127.0.0.1:7890）的 SSH 反向隧道拉取：
  `ssh -fNR 7890:localhost:7890 user@10.131.102.144`（145 同理）
- containerd 代理配置：/etc/systemd/system/containerd.service.d/*.conf（HTTP_PROXY=127.0.0.1:7890）
- 隧道断了会导致镜像拉取失败（ImagePullBackOff），重新建立隧道即可，无需重启 containerd（ctr pull 场景）

## 常用命令（在 144 上执行，kubectl 需 sudo）

```bash
kubectl get pods -A                       # 查看所有 Pod
kubectl get svc -A | grep NodePort        # 查看对外端口
kubectl logs -n spark deploy/spark-master # 查看 Spark master 日志
kubectl logs -n flink deploy/flink-jobmanager # 查看 Flink JobManager 日志
kubectl top nodes                         # 节点资源使用
```

## 已占用 NodePort 汇总

| 端口 | 服务 |
|------|------|
| 30000 / 30083 / 30002 | Hive HS2 / Metastore / Web UI |
| 30820 / 30870 / 30888 | Hadoop HDFS RPC / NameNode UI / YARN UI |
| 32129 | K8s Dashboard (HTTPS) |
| 32080 | Spark Master Web UI |
| 32181 | Flink Web UI |
