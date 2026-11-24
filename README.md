# 企业智能合同审查平台

基于 FastAPI + Vue 3 + LangGraph 的合同智能审查系统：上传合同后自动完成条款抽取、风险识别、修改建议生成、人工复核与报告导出。

## 功能

- **AI 审查流水线**：解析 → 条款抽取 → 规则 + LLM 风险识别 → 修改建议 → 人工复核 → 报告生成（LangGraph 编排，Celery 异步执行）
- **RAG 规则库**：内置 8 条合规规则（签约主体、标的、付款、违约责任等），BGE 向量检索 + Milvus，支持规则增删改
- **风险分级**：高/中/低三级风险，附条款定位、依据、置信度、修改前后对照
- **人工复核**：采纳 / 驳回 / 修改建议，自动生成修订版本记录
- **报告导出**：TXT / DOCX，含风险明细、建议理由与引用
- **数据看板**：任务量、风险分布、平均耗时、采纳率等统计
- **账号权限**：RBAC（管理员 / 审查员 / 普通员工），JWT 登录，操作审计
- **可观测性**：健康检查、Prometheus 指标、Grafana 面板（Docker 部署时启用）

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.13、FastAPI、SQLAlchemy 2、Celery、LangGraph |
| 前端 | Vue 3、TypeScript、Vite、Element Plus、ECharts、Pinia |
| 存储 | PostgreSQL / SQLite、Redis、Milvus（本地为 milvus-lite） |
| 模型 | DeepSeek（OpenAI 兼容协议）、BGE 中文向量模型（fastembed） |
| 部署 | Docker Compose、Nginx、Prometheus、Grafana |

## 快速开始

### 方式一：Docker 一键启动（推荐试用）

需要 Docker 与 Docker Compose。

```bash
cd deploy
cp .env.example .env
# 编辑 .env，填入你的模型服务：
#   LLM_BASE_URL=https://api.deepseek.com/v1
#   LLM_API_KEY=sk-xxxx
docker compose up -d --build
```

启动后访问：

- 前端：http://localhost:8080
- 后端 API 文档：http://localhost:8000/docs
- Prometheus：http://localhost:9090 ，Grafana：http://localhost:3000

> 首次构建会下载依赖与 BGE 向量模型，耗时较长；Milvus 栈较重，机器内存建议 8GB 以上。

### 方式二：本地开发（SQLite + 本地 Redis，最轻量）

依赖：Python 3.11+、Node.js 18+、Redis。

```bash
# 1. 模型配置
cp .env.example .env        # 填入 LLM_API_KEY
# 若使用 SQLite，保持 DATABASE_URL 注释状态即可

# 2. 后端
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m app.db_init           # 建表 + 预置账号/角色/规则（幂等；首次会下载向量模型）
uvicorn app.main:app --port 8000

# 3. Celery Worker（新终端，Windows 必须 --pool=solo）
cd backend
celery -A app.worker.celery_app worker --pool=solo -l info

# 4. 前端（新终端）
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 。

Redis 可用容器快速启动：`docker run -d --name redis -p 6379:6379 redis:7-alpine`

> 本机若已有 PostgreSQL，可在 `.env` 中配置 `DATABASE_URL=postgresql+psycopg2://user:pass@127.0.0.1:5432/contract`，首次连接前先建库，再执行 `python -m app.db_init`。

## 内置账号

| 账号 | 密码 | 角色 | 权限 |
|---|---|---|---|
| admin | admin123 | 管理员 | 全部功能 |
| lead | 123456 | 审查主管 | 复核、报告 |
| staff | 123456 | 员工 | 上传、查看 |

> 仅为演示数据，部署到公网前请修改密码与 `JWT_SECRET`。

## 试用流程

1. 登录后进入「合同审查」，上传仓库根目录的示例文件 `high_risk_contract.txt`
2. 点击开始审查，等待流水线完成（首次调用模型约数十秒）
3. 在待复核列表逐条采纳/驳回建议，提交后生成报告
4. 详情页可下载 TXT / DOCX 报告，「数据看板」查看统计

## 配置项

| 变量 | 说明 | 默认 |
|---|---|---|
| `DATABASE_URL` | 数据库连接串 | `sqlite:///storage/contract.db` |
| `REDIS_URL` | Celery Broker / 事件通道 | `redis://localhost:6379/0` |
| `LLM_BASE_URL` | 模型服务地址（OpenAI 兼容） | `http://localhost:8001/v1` |
| `LLM_API_KEY` | 模型服务密钥 | `sk-local` |
| `LLM_MODEL` | 模型名称 | `deepseek-chat` |
| `JWT_SECRET` | JWT 签名密钥 | `dev-secret-change-me` |
| `MILVUS_URI` | Milvus 地址；留空用 milvus-lite | 空 |
| `STORAGE_DIR` | 上传与报告目录 | `storage/` |

## 目录结构

```
backend/
  app/
    api/        # REST 接口（认证、合同、审查、规则、知识库、审计、看板、监控）
    agents/     # LangGraph 审查工作流
    services/   # 解析、LLM、RAG、报告、权限等
    models/     # SQLAlchemy 模型
    core/       # 配置、数据库、安全
  requirements.txt
frontend/
  src/          # Vue 3 页面、组件、API 封装、路由
deploy/
  docker-compose.yml
  nginx/ prometheus/ grafana/
  scripts/      # Windows 启动/停止脚本
docs/           # 需求分析、技术设计文档
storage/        # 上传文件、报告、本地数据库（运行时生成）
```

## 安全说明

- 仓库不包含 `.env`，请基于 [.env.example](.env.example) 自行创建
- 生产环境必须修改 `JWT_SECRET` 与默认账号密码
- 如密钥曾以明文形式共享，请在模型服务商处吊销并重新生成

## 文档

- [需求分析文档](docs/需求分析文档.md)
- [技术设计文档](docs/技术设计文档.md)
- [需求与技术设计（完整版）](docs/企业智能合同审查平台-需求与技术设计.md)
