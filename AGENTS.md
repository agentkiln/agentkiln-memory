# AGENTS.md

本文件约束 AgentKiln Memory 项目的后续开发。

## 项目定位

本项目面向 2026 Agent Memory Challenge 的文本记忆赛道，实现参赛方自行部署的同步 `Add` 和 `Search` 接口。Search 只返回记忆证据，不生成最终答案。

## 必须遵守

- 所有记忆、词法索引、向量候选、邻接窗口和缓存必须按精确 `user_id` 隔离。
- Add 返回成功前必须完成持久化和索引，使记录立即可检索。
- 相同 `request_id` 和相同请求体必须幂等；相同 `request_id` 携带不同请求体时必须返回冲突。
- Search 返回的 `data` 必须按相关性排序，数量不得超过 `top_k`。
- 不得在仓库中提交密钥、`.env`、数据库、评测私有数据、日志或凭据文件。
- 线上部署使用 `AML_PRODUCTION=1`、`AML_LLM_MODE=competition` 和随机生成的 `AML_API_KEY`。
- 正式运行模型按当前赛事合同配置；不得在 `competition` 模式缺少凭证时静默降级。
- 只有真实执行过的步骤才能写入验证结果；没有官方成绩时不得暗示已经获得名次。

## 工程约定

- 运行测试：`pytest -q`
- 运行隐私扫描：`python scripts/privacy_scan.py --root .`
- 本地端到端检查：`python scripts/local_verify.py --port 8123 --concurrency 24`
- 上线契约检查：`python scripts/ops_contract.py --base-url https://your-domain.example --api-key "$MEMORY_SYSTEM_KEY"`
- 重启恢复检查：`python scripts/recovery_check.py --base-url http://127.0.0.1:8000 --api-key "$AML_API_KEY" --container agentkiln-memory`
- 提交前发布检查：`python scripts/release_check.py --repository-url ... --add-url ... --search-url ... --health-url ...`

不再使用的项目文件移入 `del/`，不要直接删除。真实测试临时文件由测试框架自行清理。

