# OMOP 医疗数据治理平台

## 1. 项目概述

AI Native 医疗数据治理平台，基于 **意图驱动 (Intent-driven)** 架构，通过大模型驱动的 MCP Tools 实现从医院异构数据到 OMOP CDM 标准模型的全自动/半自动转化。

### 核心技术原则

- **存算分离**：计算资源（Doris/Argo）与数据存储（MinIO/Iceberg）解耦
- **全量 MCP 化**：所有业务逻辑封装为 MCP 工具，供 AI 编排
- **Generative UI**：前端不预设死路由，根据后端指令动态渲染交互组件

---

## 2. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户交互层                               │
│                  http://10.131.102.114:3000                    │
│                   Next.js + Tailwind CSS                       │
└─────────────────────────────┬───────────────────────────────────┘
                              │ SSE 流式请求
┌─────────────────────────────▼───────────────────────────────────┐
│                     AI 编排中枢 (Backend)                         │
│                  http://10.131.102.114:8000                      │
│              Python FastAPI + MCP SDK + SSE 流式输出              │
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐         │
│  │意图路由      │   │ Tool 执行器   │   │ LLM 流式接口  │         │
│  │(Qwen3-80B)  │──▶│ (5个核心工具) │──▶│ (OpenAI兼容) │         │
│  └──────────────┘   └──────────────┘   └──────────────┘         │
└─────────────────────────────┬───────────────────────────────────┘
                              │ MCP Tool 调用
         ┌────────────────────┼────────────────────┐
         ▼                    ▼                    ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│  Ingestion   │   │ Terminology  │   │  Workflow    │
│  Tool        │   │  Tool        │   │  Tool        │
└──────┬───────┘   └──────┬───────┘   └──────┬───────┘
       │                  │                   │
       ▼                  ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ SeaTunnel    │   │ PostgreSQL   │   │ Argo         │
│ + Argo       │   │ (pgvector)   │   │ Workflows    │
│ Workflows    │   │              │   │              │
└──────────────┘   └──────────────┘   └──────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                      数据存储与元数据层                             │
│                                                                   │
│   Datahub (GMS)     MinIO (Iceberg)      Doris      Neo4j/ES       │
│   :9002              :9001             :8030     7474/9202       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 前端 | Next.js 15 + Tailwind CSS | 对话界面 + 动态组件渲染 |
| 后端 | Python 3.11 + FastAPI | AI Gateway + MCP 工具 |
| LLM | Qwen3-80B (OpenAI 兼容接口) | 意图理解 + 工具编排 |
| 采集 | Apache SeaTunnel + Argo Workflows | 数据同步任务提交 |
| 术语 | PostgreSQL + pgvector | 语义术语匹配 |
| 元数据 | Datahub | 数据资产全景 |
| 存储 | MinIO + Iceberg | 湖仓一体存储 |
| 计算 | Apache Doris | OLAP 查询引擎 |

---

## 4. 项目结构

```
/opt/omop-platform/
├── backend/                      # AI Gateway 后端
│   ├── main.py                  # FastAPI 主程序 + MCP Tools
│   ├── requirements.txt         # Python 依赖
│   └── Dockerfile              # 容器化部署
│
└── frontend/                     # Next.js 前端
    ├── app/
    │   ├── page.tsx            # 对话页面 + 动态组件
    │   ├── layout.tsx          # 根布局
    │   ├── globals.css          # 深色主题样式
    │   └── api/chat/route.ts   # /api/chat SSE 代理
    ├── package.json
    ├── tailwind.config.ts
    └── tsconfig.json
```

---

## 5. MCP Tools 接口

### A. ingestion_submit
- **功能**：生成 SeaTunnel 配置并提交 Argo Workflow
- **输入**：源库类型/地址/表名 + 目标 Iceberg 表名 + 字段映射
- **输出**：任务提交状态 + PROGRESS_BAR UI

### B. terminology_match
- **功能**：pgvector 语义匹配本地术语 → OMOP 标准词表
- **输入**：术语字符串 + 词表类型 (Drug/Condition/Procedure/Observation)
- **输出**：候选映射列表 + SINGLE_SELECT_CONFIRM UI (低置信度时)

### C. workflow_status
- **功能**：查询 Argo Workflow 任务状态
- **输入**：Workflow 名称 + 命名空间
- **输出**：任务阶段 + Pod 列表 + PROGRESS_BAR / LOG_VIEW UI

### D. datahub_search
- **功能**：搜索 Datahub 元数据
- **输入**：搜索关键词 + 平台过滤
- **输出**：表结构、血缘关系列表

### E. doris_query
- **功能**：对 Doris 执行 SQL 查询
- **输入**：SELECT 语句 + 结果集上限
- **输出**：结果集 + 列信息

---

## 6. 动态组件协议 (ui_action)

后端返回结构化指令，前端根据 `type` 渲染对应组件：

| type | 渲染组件 | 触发场景 |
|------|----------|----------|
| `PROGRESS_BAR` | 任务进度条 | 工作流运行中 |
| `SINGLE_SELECT_CONFIRM` | 单选确认框 | 术语低置信度匹配 |
| `FORM` | 配置表单 | 缺少参数需用户填写 |
| `LOG_VIEW` | 日志视图 | 工作流失败查看详情 |

---

## 7. 已部署服务状态

| 服务 | 地址 | 端口 | 状态 |
|------|------|------|------|
| **OMOP Backend** | http://10.131.102.114 | 8000 | ✅ 运行中 |
| **OMOP Frontend** | http://10.131.102.114 | 3000 | ✅ 运行中 |
| SeaTunnel | http://10.131.102.114 | 8080 | ✅ 运行中 |
| Argo Workflows | https://10.131.102.114 | 2746 | ✅ 运行中 |
| Datahub Frontend | http://10.131.102.114 | 9002 | ✅ 运行中 |
| Elasticsearch | http://10.131.102.114 | 9202 | ✅ 运行中 |
| Neo4j | http://10.131.102.114 | 7474/7687 | ✅ 运行中 |
| Doris | http://10.131.102.114 | 8030 | ✅ 运行中 |
| MinIO | http://10.131.102.114 | 9001 | ✅ 运行中 |

---

## 8. 启动方式

### 后端
```bash
cd /opt/omop-platform/backend
pip install -r requirements.txt
python3 main.py
# 或容器: docker build -t omop-backend . && docker run -p 8000:8000 omop-backend
```

### 前端
```bash
cd /opt/omop-platform/frontend
npm install
npm run dev
```

---

## 9. 环境变量配置

后端通过环境变量配置（修改 `/opt/omop-platform/backend/main.py` 顶部）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_BASE_URL` | https://dashscope.aliyuncs.com/compatible-mode/v1 | LLM API 地址 |
| `LLM_API_KEY` | your-api-key | **需配置** LLM 密钥 |
| `LLM_MODEL` | qwen3-80b | 模型名称 |
| `ARGO_SERVER` | https://10.131.102.114:2746 | Argo Server 地址 |
| `ARGO_TOKEN` | (空) | **需配置** Argo 认证令牌 |
| `MINIO_ENDPOINT` | 10.131.102.114:9000 | MinIO 地址 |
| `MINIO_ACCESS_KEY` | minioadmin | MinIO 用户 |
| `MINIO_SECRET_KEY` | minioadmin123 | MinIO 密码 |
| `PG_HOST` | 10.131.102.114 | PostgreSQL 地址 |
| `PG_PORT` | 5432 | pgvector 端口 |
| `PG_DATABASE` | postgres | 数据库名 |
| `PG_USER` | postgres | 用户名 |
| `PG_PASSWORD` | postgres | 密码 |

---

## 10. 业务流程示例

```
用户: "把 HIS 的门诊记录同步到 OMOP Drug Exposure 表"

     │
     ▼
┌─────────────────────┐
│  AI 解析意图         │
│  → ingestion_submit │
└─────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│  PROGRESS_BAR               │
│  "正在生成 SeaTunnel 配置"  │
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│  Argo 任务提交成功         │
│  workflow_name: omop-sync  │
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│  PROGRESS_BAR              │
│  任务运行中... 60%         │
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│  terminology_match         │
│  5条新药品名称无法自动识别 │
│  SINGLE_SELECT_CONFIRM     │
│  用户手动选择映射          │
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│  治理完成                   │
│  数据入库 Doris             │
│  Datahub 更新血缘关系      │
└─────────────────────────────┘
```

---

## 11. 待完善事项

1. **LLM 对接**：配置 `LLM_API_KEY` 并替换为 Qwen3-80B 真实接口
2. **Datahub GMS**：修复 MySQL 连接问题，启用真实元数据查询
3. **Argo 认证**：配置 `ARGO_TOKEN` 实现真实工作流提交
4. **PostgreSQL/pgvector**：部署并初始化 OMOP 标准术语库
5. **Doris 连接**：对接真实查询（当前为模拟数据）
6. **用户认证**：增加登录和权限管理
7. **任务持久化**：数据库存储对话历史和任务记录



阶段1（立即可做）：

重构后端代码，将真实连接器与工具实现分离
完善前端 UI Action 组件（特别是 DYNAMIC_FORM）
阶段2（需要测试）：

逐一实现真实连接器（先从一个组件开始，比如 Doris）
测试完整的数据同步流程
阶段3（增强）：

引入真正的 MCP SDK
实现更复杂的对话状态机