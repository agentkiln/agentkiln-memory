# AGENTS.md

本文件是 AI Agent 进入 AgentKiln Memory 的入口，面向后续开发和验证。README.md 面向人类读者，重点说明项目用途和快速开始；本文件说明项目约束、命令入口和验证闭环。细节优先查代码和 docs 下的文档，不在本文件重复维护。

## 项目定位

AgentKiln Memory 面向 2026 Agent Memory Challenge 的文本记忆赛道，实现参赛方自行部署的同步 `Add` 和 `Search` 接口。Search 只返回记忆证据，不生成最终答案。

技术栈和结构：

- Python 3.10 及以上，FastAPI，Pydantic，SQLite FTS5，Uvicorn。
- `app/`：接口模型、配置、SQLite 存储、检索、证据打包和服务入口。
- `eval/`：离线检索指标和 JSONL 评测入口。
- `scripts/`：本地验证、公开契约检查、恢复检查、发布检查和隐私扫描。
- `tests/`：接口契约、隔离、持久化、并发、时间检索和工具验证。
- `deploy/`：Caddy 公网 HTTPS 反向代理示例和部署说明。
- `docs/`：构建状态、项目状态和提交材料说明。

## 必须遵守

- 所有记忆、词法索引、向量候选、邻接窗口和缓存必须按精确 `user_id` 隔离。
- Add 返回成功前必须完成持久化和索引，使记录立即可检索。
- 相同 `request_id` 和相同请求体必须幂等；相同 `request_id` 携带不同请求体时必须返回冲突。
- Search 返回的 `data` 必须按相关性排序，数量不得超过 `top_k`。
- 不得在仓库中提交密钥、`.env`、数据库、评测私有数据、日志或凭据文件。
- 线上部署使用 `AML_PRODUCTION=1`、`AML_LLM_MODE=competition` 和随机生成的 `AML_API_KEY`。
- 正式运行模型按当前赛事合同配置；不得在 `competition` 模式缺少凭证时静默降级。
- 只有真实执行过的步骤才能写入验证结果；没有官方成绩时不得暗示已经获得名次。
- 修改接口行为时，必须同步更新测试、README 示例和提交材料。
- 修复线上问题后，优先补一个能复现该问题的测试，再提交修复。

## 提交规范

- Git 提交人名称统一使用 `chronicle`，邮箱使用项目维护者邮箱；不得写入其他作者信息。
- 提交信息使用 `type: short description`，类型限定为 `feat`、`fix`、`test`、`docs`、`chore`、`security`、`perf`、`refactor`。
- 描述使用英文小写短句，说明这次提交改变的行为，不写“update code”这类空泛描述。
- 一个提交只处理一类变化。修复 bug、增加功能、文档更新和依赖调整不要混在同一次提交。
- 修复缺陷时优先先写失败测试，再改实现，再确认测试通过。
- 提交前必须运行 `pytest -q` 和 `python scripts/privacy_scan.py --root .`。
- 提交前必须检查 `git status --short`，确保没有数据库、日志、密钥、`.env`、临时数据或 `del/` 内容被加入暂存区。
- 正式评测冻结后，不再改写该版本的接口行为；新实验使用新提交并通过独立部署验证。
- 如果包含安全问题修复，提交信息必须以 `security:` 开头；如果包含性能优化，提交信息必须以 `perf:` 开头。
- 如果一次提交同时包含多个目的，拆分提交，不要用一个大提交混合功能、修复、文档和依赖调整。

## 工程约定

| 目标 | 命令 |
|---|---|
| 单元测试 | `python -m pytest -q` |
| 隐私扫描 | `python scripts/privacy_scan.py --root .` |
| 本地端到端 | `python scripts/local_verify.py --port 8123 --concurrency 24` |
| 线上接口契约 | `python scripts/ops_contract.py --base-url https://your-domain.example --api-key "$MEMORY_SYSTEM_KEY"` |
| 重启恢复 | `python scripts/recovery_check.py --base-url http://127.0.0.1:8000 --api-key "$AML_API_KEY" --container agentkiln-memory` |
| 发布检查 | `python scripts/release_check.py --repository-url ... --add-url ... --search-url ... --health-url ...` |

## 验证闭环

修改代码后按以下顺序推进，不要停在代码编辑本身。

1. 先运行与改动最接近的测试。
2. 再运行 `python -m pytest -q` 和 `python scripts/privacy_scan.py --root .`。
3. 涉及服务启动或接口行为时，运行 `python scripts/local_verify.py`。
4. 涉及公网部署时，运行 `scripts/ops_contract.py` 和 `scripts/recovery_check.py`。
5. 涉及提交或冻结版本时，运行 `scripts/release_check.py`。

如果规则只写在文档里，Agent 和人都可能在压力下违反。能让脚本检查的规则，要加到 `scripts/privacy_scan.py`、`scripts/release_check.py` 或 `tests/` 中。

## 文档导航

- `README.md`：接口示例、运行方式、配置项和部署入口。
- `docs/BUILD_STATUS.md`：当前完成项、未完成项和外部阻塞。
- `docs/STATE.md`：最近一次验证记录和下一项任务。
- `SUBMISSION.md`：提交材料草稿。
- `DISCLOSURE.md`：方法和完整性说明。
- `SECURITY.md`：密钥处理和评测数据删除要求。
- `deploy/README.md`：公网部署、HTTPS 和契约检查步骤。

不再使用的项目文件移入 `del/`，不要直接删除。真实测试临时文件由测试框架自行清理。

## 规则维护

AGENTS.md 不是写完就锁定的文档。每次发现 AI 犯了一个会影响接口、隔离、安全或验证结果的错误，就判断应该把规则放在哪里：

- 违反后会直接写出错误代码的硬性规则，加入本文件。
- 只影响某个模块的开发细节，加入对应 `docs/` 文档或代码注释。
- 可以用脚本检查的规则，直接加入自动化检查。
