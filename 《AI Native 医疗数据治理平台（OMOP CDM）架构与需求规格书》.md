《AI Native 医疗数据治理平台（OMOP CDM）架构与需求规格书》。

---

## 1. 项目愿景与核心架构

构建一个**“以意图为中心” (Intent-driven)** 的医疗数据治理底座。抛弃传统的多级菜单，通过大模型（Qwen3-80B）驱动 MCP Tools，实现从医院异构数据到 OMOP CDM 标准模型的全自动/半自动转化。

### **核心设计原则**

- **存算分离**：计算资源（Doris/Argo）与数据存储（MinIO/Iceberg）解耦。
- **全量 MCP 化**：所有业务逻辑封装为 MCP 工具，供 AI 编排。
- **Generative UI**：前端不预设死路由，根据后端指令动态渲染交互组件。

### **核心技术架构&技术栈**

| 层级          | 技术栈                          |
| ------------- | ------------------------------- |
| 前端          | Next.js + Tailwind + Shadcn/ui  |
| 后端          | Python (FastAPI) + MCP SDK      |
| 数据采集      | Apache SeaTunnel                |
| 元数据管理    | Datahub                         |
| 向量数据库    | PostgreSQL (pgvector) or Milvus |
| 存储层 (存)   | MinIO                           |
| 计算引擎 (算) | Apache Doris                    |
| 任务编排调度  | Argo Workflows                  |
| 部署          | Kubernetes + Docker             |

---

## 2. 关键层级需求定义

### **2.1 前端：智能交互层 (Next.js + Shadcn/ui)**

- **对话框枢纽**：实现一个流式聊天界面，支持 Markdown、代码高亮以及自定义组件注入。
- **动态组件渲染器**：根据后端返回的 `ui_action` 协议，动态加载配置表单（Form）、差异比对（Diff）、任务进度条（Progress）。
- **状态保持**：即使在长周期的治理任务中，也要通过会话 ID 保持任务上下文的可见性。

### **2.2 后端：AI 编排中枢 (FastAPI + MCP SDK)**

- **意图路由**：利用 Qwen3 解析用户意图，匹配对应的 MCP Server。
- **协议转换**：将 MCP Tool 的原始输出封装成带 UI 描述符的结构化 JSON。
- **安全网关**：在执行任何写操作（如删除 Doris 表、启动同步任务）前，强制触发 `action_required` 确认流程。

### **2.3 元数据与存储 (Datahub + MinIO + Iceberg)**

- **资产全景**：Datahub 需实时抓取医院源系统（Oracle/SQL Server）与结果集（Doris）的元数据。
- **湖仓一体**：所有治理过程中的增量数据必须以 Iceberg 表格式存于 MinIO，支持 Time Travel（快照回溯）。

---

## 3. 核心 MCP Tools 接口规格 (Vibe Coding 参考)

为了方便你进行 Vibe Coding，以下是必须实现的三个核心工具集定义：
    
### **A. 采集工具 (Ingestion Tool)**

- **输入**：源库连接信息、目标 Iceberg 表名。
- **逻辑**：生成 SeaTunnel 配置文件并提交至 K8s 运行。
- **交互**：若连接失败，返回 `DYNAMIC_FORM` 请求用户修正 IP 或权限。

### **B. 术语映射工具 (Terminology Tool)**

- **输入**：本地术语字符串、目标词表。
- **逻辑**：调用 **pgvector** 进行语义匹配。
- **交互**：低置信度时返回 `SINGLE_SELECT_CONFIRM` 组件，让用户在对话框中点选。

### **C. 调度监控工具 (Workflow Tool)**

- **输入**：Argo Workflow 名称/ID。
- **逻辑**：查询 Argo Server API 获取当前 Pod 状态。
- **交互**：返回 `PROGRESS_BAR` 或 `LOG_VIEW` 组件。

---

## 4. 业务流程：从原始数据到 OMOP 映射

1. **用户**：“把 HIS 的门诊记录同步过来，映射到 OMOP 的 Drug Exposure 表。”
2. **AI (via Metadata Tool)**：查询 Datahub，确认源表 `HIS_PRESCRIPTION` 结构，发现缺少日期格式配置。
3. **UI 交互**：对话框弹出表单，用户确认日期字段格式。
4. **AI (via Ingestion & Workflow Tool)**：生成 SeaTunnel 脚本 提交 Argo 任务 在对话框显示进度条。
5. **AI (via Terminology Tool)**：发现 5 条新药品名称无法自动识别，弹出确认框请用户手动映射。
6. **治理完成**：数据入库 Doris，Datahub 更新血缘关系。

---

## 5. 部署与环境要求 (K8s)

- **基础组件**：使用 Helm 部署 Datahub（含 Kafka/ES）、MinIO、Argo Workflows。
- **计算集群**：部署 Apache Doris 存算分离集群（FE + BE）。
- **模型节点**：Qwen3-80B 需部署在具备 GPU 资源的节点，并通过 FastAPI 暴露兼容 OpenAI 或 MCP 的接口。

