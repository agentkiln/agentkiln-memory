<div align="center">

<img src="docs/assets/agentkiln-logo.svg" alt="AgentKiln Memory" width="160"/>

# AgentKiln Memory

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?logo=fastapi&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%2B-4169E1?logo=postgresql&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-FTS5-003B57?logo=sqlite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

![CI](https://github.com/agentkiln/agentkiln-memory/actions/workflows/ci.yml/badge.svg)
![Deploy](https://github.com/agentkiln/agentkiln-memory/actions/workflows/deploy-pandastack.yml/badge.svg)


[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

**面向 AI Agent 的证据型长期记忆服务。**

[English](README.md) | 简体中文

</div>

## 目录

- [项目定位](#项目定位)
- [功能特性](#功能特性)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [API 说明](#api-说明)
- [检索流水线](#检索流水线)
- [配置项](#配置项)
- [部署](#部署)
- [测试](#测试)
- [项目结构](#项目结构)
- [参与贡献](#参与贡献)
- [安全](#安全)
- [许可协议](#许可协议)

## 项目定位

AgentKiln Memory 是一个证据型长期记忆服务，为 AI Agent 提供基于源消息的记忆存储与检索能力。系统按精确 `user_id` 隔离每一条记忆，使用词法检索与向量检索的混合流水线，按相关性返回原始源消息，不会生成答案。

这个设计带来的直接收益是可审计：下游 Agent 能看到记忆系统实际返回了什么，便于验证没有幻觉、便于定位检索质量问题，也便于在评测环境中检验记忆能力的真实水平。

同样适用于生产环境的 Agent 记忆管道。

## 功能特性

- **同步 Add/Search API**：FastAPI 与 Pydantic 校验，返回值契约明确
- **严格用户隔离**：所有记忆、词法索引、向量候选和缓存键都按精确 `user_id` 隔离
- **幂等写入**：相同 `request_id` 与相同请求体可安全重试；相同 `request_id` 携带不同请求体返回 HTTP 409
- **混合检索**：SQLite FTS5 词法搜索与向量余弦相似度，通过倒数排序融合
- **邻接窗口扩展**：在同一会话内扩展匹配证据的相邻消息，恢复对话上下文
- **时间意图检测**：识别 latest 和 earliest 查询，按时间重新排序证据
- **Token 预算控制**：证据窗口遵循可配置的 token 预算，返回数量不超过 `top_k`
- **PostgreSQL 或 SQLite**：生产环境使用 PostgreSQL，本地开发使用 SQLite 与 FTS5
- **OpenAI 兼容嵌入**：任何提供 `POST /v1/embeddings` 的服务都可用，包括 Jina、OpenRouter、NVIDIA NIM 和 SiliconFlow
- **生产部署**：Docker、Compose、Caddy HTTPS 反向代理、健康检查和 GitHub Actions 自动部署
- **隐私优先**：不记录请求体，不持久化凭据，评测数据在 30 天内删除

## 系统架构

```text
                       +---------------------+
                       |   FastAPI 服务      |
                       |  /add  /search /v1  |
                       +----------+----------+
                                  |
                    +-------------+-------------+
                    |                           |
              +-----v------+             +------v------+
              | MemoryLLM  |             | MemoryService|
              |  嵌入调用   |             |  用户隔离    |
              |  消息标注   |             |  缓存管理    |
              |  查询规划   |             +------+------+
              +-----+------+                    |
                    |                           |
          +---------v----------+     +----------v-----------+
          |  嵌入服务提供方     |     |    存储后端           |
          | (OpenAI 兼容)      |     | PostgreSQL / SQLite  |
          +--------------------+     +----------+-----------+
                                                |
                                     +----------v-----------+
                                     |      检索层          |
                                     |  FTS5 词法搜索       |
                                     |  向量余弦相似度      |
                                     |  倒数排序融合        |
                                     |  窗口扩展            |
                                     |  时间排序            |
                                     +----------------------+
```

服务暴露同步 REST 端点。Add 请求在单次同步调用中完成校验、标注、嵌入和持久化，记录立即可检索。Search 请求先通过 LLM 辅助的意图提取生成查询计划，再路由到词法和向量两个通道，融合、扩展、排序后打包成受 token 预算控制的窗口。

## 快速开始

### 本地运行

```bash
git clone https://github.com/agentkiln/agentkiln-memory.git
cd agentkiln-memory

python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt

AML_LLM_MODE=off uvicorn app.main:app --host 0.0.0.0 --port 8000
```

服务在 8000 端口启动。`GET /health` 无需认证。

### 添加记忆

```bash
curl -X POST http://127.0.0.1:8000/add \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "run:conv:chunk-0",
    "messages": [
      {
        "role": "user",
        "timestamp": 1704067200000,
        "content": "我最喜欢喝茉莉花茶"
      }
    ],
    "user_id": "user-123",
    "session_id": "session-456"
  }'
```

### 搜索

```bash
curl -X POST http://127.0.0.1:8000/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "我最喜欢喝什么茶",
    "options": ["咖啡", "茉莉花茶"],
    "user_id": "user-123",
    "top_k": 5
  }'
```

### 运行测试

```bash
pytest -q
python scripts/privacy_scan.py --root .
```

单元测试和集成测试覆盖 API 契约、用户隔离、持久化、并发、时间检索、模型调用和工具验证。

## API 说明

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 服务健康状态、版本、LLM 模式和模型就绪状态 |
| `POST` | `/add` | 存储消息，支持幂等和冲突检测 |
| `POST` | `/search` | 检索排序后的证据，不生成答案 |
| `POST` | `/v1/memory/add` | `/add` 的别名 |
| `POST` | `/v1/memory/search` | `/search` 的别名 |

### Add 请求

```json
{
  "request_id": "eval:run:conv:chunk-0",
  "messages": [
    {
      "role": "user",
      "timestamp": 1704067200000,
      "content": "我最喜欢喝茉莉花茶"
    }
  ],
  "user_id": "eval:run:conv",
  "session_id": "eval:run:sample:0"
}
```

- `request_id`：用于去重和重试安全的唯一标识
- `messages`：1 到 200 条消息，每条包含 `role`、`content` 和可选 `timestamp`
- `user_id`：严格隔离边界
- `session_id`：会话分组，用于邻接窗口扩展

### Add 响应

```json
{
  "success": true,
  "request_id": "eval:run:conv:chunk-0",
  "user_id": "eval:run:conv",
  "session_id": "eval:run:sample:0"
}
```

### Search 请求

```json
{
  "query": "我最喜欢喝什么茶",
  "options": ["咖啡", "茉莉花茶"],
  "user_id": "eval:run:conv",
  "top_k": 100
}
```

- `query`：搜索文本，1 到 8000 字符
- `options`：可选的候选项，用于选项匹配打分
- `top_k`：1 到 100，返回证据窗口的最大数量

### Search 响应

```json
{
  "data": [
    {
      "id": "mem_123",
      "content": "[mem_123 | user | 2024-01-01T00:00:00Z] 我最喜欢喝茉莉花茶",
      "score": 0.91,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ]
}
```

每个条目是包裹在会话窗口头中的原始源消息。系统不会改写、总结或生成内容。

### 认证

配置 `AML_API_KEY` 后，Add 和 Search 支持三种认证方式：

| 方式 | Header | 格式 |
|------|--------|------|
| Bearer | `Authorization` | `Bearer <key>` |
| Token | `Authorization` | `Token <key>` |
| API Key | `X-Api-Key` | `<key>` |

健康检查无需认证。`AML_API_KEY` 为空时，Add 和 Search 不要求认证。

## 检索流水线

搜索流程经过五个阶段：

1. **查询分析**：LLM 调用从查询中提取检索线索、切面和时间意图。`off` 或 `dev_mock` 模式下，仅使用词法特征驱动检索。

2. **词法搜索**：SQLite FTS5 或 PostgreSQL 全文搜索，使用 BM25 排序、Unicode 规范化、Porter 分词和 CJK n-gram。

3. **向量搜索**：查询嵌入后与存储向量比较余弦相似度，只考虑相同嵌入模型和相同维度的向量。写入时每次最多发送 10 条文本，符合 `text-embedding-v4` 的批量限制。

4. **倒数排序融合**：两个候选列表按 `1 / (60 + rank)` 评分合并，然后按最小相似度阈值过滤。

5. **窗口扩展与排序**：匹配候选扩展为包含同一会话相邻消息的窗口。规则排序结合词覆盖、选项匹配、短语匹配和时间意图。没有时间意图的查询会使用已配置的重排序模型决定最终证据顺序；调用 `qwen3.7-text-rerank` 时，从规则排序结果中最多选取 500 条候选。模型暂时不可用时使用规则排序，并在下次搜索时重试。询问最早或最新记录时，保留按时间排序的规则逻辑。

## 配置项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AML_DATABASE_PATH` | `data/memory.db` | SQLite 数据库路径 |
| `DATABASE_URL` | 空 | PostgreSQL 连接 URL；设置后使用 PostgreSQL 后端 |
| `AML_PRODUCTION` | 空 | 设为 `1` 启用比赛模式和 API key 认证 |
| `AML_LLM_MODE` | `off` | `off`、`dev_mock` 或 `competition` |
| `AML_API_KEY` | 空 | 可选的 Add/Search 认证密钥 |
| `OPENAI_API_KEY` | 空 | 运行时模型凭据 |
| `OPENAI_MODEL` | `gpt-4o-mini` | Add/Search LLM 模型 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 base URL |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-v4` | 嵌入模型 |
| `OPENAI_EMBEDDING_BASE_URL` | 回退到 `OPENAI_BASE_URL` | 可选的独立嵌入端点 |
| `OPENAI_EMBEDDING_API_KEY` | 回退到 `OPENAI_API_KEY` | 可选的独立嵌入凭据 |
| `RERANK_MODEL` | 空 | 可选的重排序模型；留空则关闭 |
| `RERANK_BASE_URL` | 回退到嵌入服务地址 | 重排序接口或 base URL |
| `RERANK_API_KEY` | 回退到嵌入服务密钥 | 可选的独立重排序凭据 |
| `AML_TIMEOUT_SECONDS` | `90` | 上游超时 |
| `AML_CANDIDATE_LIMIT` | `300` | 每个检索通道在融合前的候选数量上限 |
| `AML_MAX_OUTPUT_TOKENS` | `8000` | 证据 token 预算 |
| `AML_MAX_OUTPUT_ITEMS` | `24` | 返回证据窗口最大数量 |
| `AML_VECTOR_MIN_SIMILARITY` | `0.35` | 仅向量候选的最小相似度 |
| `AML_VECTOR_ONLY_MIN_SIMILARITY` | `0.65` | 词法无候选时更严格的阈值 |
| `AML_SEARCH_CONCURRENCY` | `32` | 进程内 Search 最大并发 |
| `AML_ADD_CONCURRENCY` | `16` | 进程内 Add 最大并发 |

使用 `qwen3.7-text-rerank` 时，`RERANK_BASE_URL` 可以填写以 `/api/v1/services/rerank/text-rerank/text-rerank` 结尾的阿里云完整接口地址。服务会使用该模型要求的嵌套 `input` 请求和 `output.results` 响应格式。

## 部署

### Docker

```bash
docker build -t agentkiln-memory .
docker run -d --name agentkiln \
  -p 8000:8000 \
  -e AML_LLM_MODE=off \
  agentkiln-memory
```

### Docker Compose

```bash
docker compose up -d
```

### 生产环境

完整生产部署指南见 [deploy/PandaStack.md](deploy/PandaStack.md)，包括托管 PostgreSQL、HTTPS 反向代理、环境变量和 GitHub Actions 自动部署。

### 验证

部署到生产环境前：

```bash
python scripts/ops_contract.py --base-url https://your-domain.example --api-key "$MEMORY_SYSTEM_KEY"
python scripts/recovery_check.py --base-url http://127.0.0.1:8000 --api-key "$AML_API_KEY" --container agentkiln-memory
python scripts/release_check.py \
  --repository-url https://github.com/agentkiln/agentkiln-memory \
  --add-url https://your-domain.example/add \
  --search-url https://your-domain.example/search \
  --health-url https://your-domain.example/health
```

## 测试

```bash
pytest -q
```

单元测试和集成测试覆盖：

- API 契约与响应 schema 校验
- 严格用户隔离与跨用户访问拒绝
- 幂等 Add 与载荷冲突检测
- 进程重启后的持久化
- 并发 Add 与 Search 操作
- 时间意图检索（latest、earliest）
- 词法规范化与 CJK 分词支持
- 隐私扫描与发布检查工具

## 项目结构

```text
agentkiln-memory/
├── app/
│   ├── main.py          # FastAPI 入口
│   ├── config.py        # 配置与环境变量
│   ├── llm.py           # 嵌入与 LLM 调用
│   ├── service.py       # 检索流水线与业务逻辑
│   ├── postgres_db.py   # PostgreSQL 存储后端
│   ├── schemas.py       # Pydantic 请求/响应模型
│   └── text.py          # 词法规范化与特征提取
├── eval/
│   └── retrieval.py     # 离线检索评测
├── scripts/
│   ├── smoke.py         # 公开 smoke 测试
│   ├── local_verify.py  # 本地端到端验证
│   ├── ops_contract.py  # 公开契约检查
│   ├── recovery_check.py # 容器重启恢复检查
│   └── release_check.py # 提交就绪检查
├── tests/               # 单元测试和集成测试
├── deploy/              # 生产部署指南
├── docs/                # 项目状态与提交材料
├── .github/workflows/   # CI 与部署自动化
├── compose.yaml         # Docker Compose 配置
├── Dockerfile           # 生产镜像
└── pyproject.toml       # 项目元数据与依赖
```

## 参与贡献

欢迎贡献。提交 Pull Request 前：

1. 运行完整测试：`pytest -q`
2. 运行隐私扫描：`python scripts/privacy_scan.py --root .`
3. 检查 `git status --short`，确保没有密钥、`.env`、数据库、日志或评测数据被暂存
4. 使用 `type: short description` 格式的提交信息，类型限定为 `feat`、`fix`、`test`、`docs`、`chore`、`security`、`perf`、`refactor`

完整开发规则和验证流程见 [AGENTS.md](AGENTS.md)。

## 安全

- 不要提交 `.env`、API key 或系统凭据
- Health 公开；Add 和 Search 可配置 Bearer、Token 或 `X-Api-Key` 认证
- 服务不记录请求体或凭据
- 所有记忆只通过精确提交的 `user_id` 检索
- 运行结束后 30 天内删除评测数据库或 Docker volume，除非主办方书面允许其他保留期限

完整安全策略见 [SECURITY.md](SECURITY.md)。

## 许可协议

MIT。完整文本见 [LICENSE](LICENSE)。
