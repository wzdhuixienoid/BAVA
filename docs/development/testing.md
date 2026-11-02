# 测试与验证

本文提供可重复的当前验证方法，不保存发布流水、历史测试数量或临时验收结论。先按 [环境配置](setup.md) 安装依赖；默认不需要模型联网的检查与真实模型评估分开执行。

## 自动检查

在仓库根目录执行：

```bash
uv run --project apps/api python scripts/check_docs.py
uv run --project apps/api ruff check apps/api scripts
uv run --project apps/api pytest apps/api/tests -m 'not postgres and not sandbox'
pnpm web:lint
pnpm web:typecheck
pnpm --filter @banking/web test
pnpm web:build
```

已安装依赖时可直接用 `apps/api/.venv/bin/python`、`apps/api/.venv/bin/ruff`；前端测试命令本体是在 apps/web 运行 `node --experimental-strip-types --test tests/*.test.mjs`。构建和开发服务不要同时写同一个 `.next` 目录。

`web:typecheck` 先运行 `next typegen`，再执行TypeScript检查，因此新检出或已清理 `.next` 的目录也可直接检查，不依赖旧构建产物。检查／构建会重新生成可删除的 `.next` 类型或缓存。

接口变化后启动当前 API，再运行 `pnpm api:generate`。生成命令读取 `${OPENAPI_URL:-http://localhost:8000/openapi.json}`，更新 `packages/api-client/src/schema.d.ts`；检查生成差异并重新 typecheck。

## PostgreSQL 集成测试

使用库名含 test 的独立数据库；测试会清理该库，不能指向业务／保留演示数据的库，也不要与同库 API 或 Worker 并行。

```bash
docker compose exec -T postgres createdb -U banking banking_regression_test
```

在 apps/api 中执行：

```bash
APP_ENVIRONMENT=test AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_regression_test \
  uv run alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_regression_test \
  uv run pytest -m postgres
```

SQLite 不能替代 PostgreSQL 锁、lease、唯一约束、迁移及并发验证。Smoke 与回归使用不同测试库；有业务数据拒绝降级是保护行为，不应清理业务库绕过。

## 安全补充验证

`test_security_v101.py` 覆盖零证据／矛盾金融回答、权限阈值、订阅查询确认与过期、页面取消审计、RFC6238向量、密钥加密、防重放和绑定锁定。`test_mfa_postgres.py` 验证跨挑战并发消费与凭据保留迁移。配置脚本幂等且不轮换原密钥。

沙箱默认测试不会启动Docker。实际隔离检查须先按[沙箱说明](../architecture/sandbox.md)构建镜像，再显式运行：

```bash
RUN_DOCKER_SANDBOX_TESTS=1 APP_ENVIRONMENT=test AUTH_MODE=development \
  apps/api/.venv/bin/python -m pytest apps/api/tests/test_code_sandbox.py -m sandbox -q
```

人工功能用例见[验收说明](../competition/acceptance.md)，本次实测范围见[提交验证记录](../competition/verification.md)，残余风险见[安全自评](../competition/security-assessment.md)。

## 功能验证地图

| 范围 | 当前回归入口 |
| --- | --- |
| 版本与文档 | test_release_version.py、test_architecture_docs.py、scripts/check_docs.py；覆盖六层导航、每个已注册 Agent 的同规格详情及所有业务 API 分组 |
| 标准技能 | test_agent_skill_catalog.py、test_standard_skill_bindings.py，覆盖资源 hash、两个运行时与三种 Python CLI |
| 工具与协议 | test_tool_contract_audit.py、test_tool_executor.py、test_runtime_parity.py |
| 个人银行与流水 | test_personal_banking_integration.py、test_statement_tool.py、test_statement_analysis.py、test_account_statement.py |
| 收款人资料维护 | test_payee_management.py、test_management_repairs.py；核对确认、本人归属、安全写锁及在用资料限制，实际付款授权由转账测试独立验证 |
| 计划与安全 | planning／plan／security／authorization 相关测试，原操作恢复及条件 grounding |
| 理财 | test_wealth.py、test_wealth_repairs.py、test_wealth_advisory.py、test_wealth_v0113.py、test_wealth_strategy.py 及 PostgreSQL 套件 |
| AA 删除 | test_aa_deletion.py、test_aa_deletion_postgres.py |
| 异常通知 | test_anomaly_notifications.py、test_anomaly_notifications_postgres.py |
| 前端 | apps/web/tests，含真实 React 组件事件／Effect 和纯逻辑测试；不等于浏览器端到端验收 |

测试文件中的版本名可能标记固定语义数据集，执行的仍是当前实现；不能据文件名判断应用版本。专项通过不能替代受影响资金路径的并发、恢复及安全验证。

## 合成数据与黄金结果

```bash
uv run --project apps/api python scripts/validate_mock_data.py
uv run --project apps/api python scripts/generate_mock_data.py
uv run --project apps/api python scripts/generate_golden_financial_metrics.py
uv run --project apps/api python scripts/generate_golden_monthly_report_core.py
```

先校验现有 fixture。生成命令会修改提交的数据和黄金预期；只有规则或合成数据确需变化时使用，并审查差异，不能为通过测试随意重写预期。API 重启后读取新 fixture，不需要清空业务数据库。

## 模型与业务 Smoke

`scripts/smoke_report_product.py` 和 `smoke_report_stability.py` 驱动 TaskRunner，使用已迁移的独立测试库和配置模型，不与同库 Worker 并行。稳定性脚本通过 `--runs` 指定次数。

真实模型评估会产生费用，并发送模型所需上下文。仅使用已授权的纯合成测试数据，核实配置的提供商和输入范围；不能直接连接现有用户数据或旧对话。输出文件放在仓库外私有临时目录，不把原始模型记录提交为产品文档。

当前理财评估入口保留数据集命名，以下在配置模型环境后执行；脚本仅接受文件名含 test 的隔离 SQLite：

```bash
PYTHONPATH=apps/api/src apps/api/.venv/bin/python scripts/evaluate_wealth_v0113.py \
  --answers-only --independent \
  --database /private/tmp/wealth_answers_test.sqlite \
  --output /private/tmp/wealth_answers_test.json
```

`--strategy` 检查策略／连续对话场景。MODEL_GENERATED 仅表示通过本次契约，不等于语言质量满分；需人工检查事实、收益暗示、问题数量和代码信息泄漏。

确定性理财 Smoke 不调用模型，新建合成用户，验证申购占用、超时恢复、成交、赎回和到账。在已迁移独立 PostgreSQL 库上执行：

```bash
APP_ENVIRONMENT=test AUTH_MODE=development MOCK_WEALTH_ENABLED=true \
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_wealth_smoke_test \
  uv run --project apps/api python scripts/smoke_wealth.py
```

Plan／Audit／Security HTTP Smoke 可通过 `PLAN_SMOKE_BASE_URL`、`AUDIT_SMOKE_BASE_URL`、`SECURITY_SMOKE_BASE_URL` 指向独立本地 API。它们可能创建转账、取消合同或触发写锁，不能指向保留演示状态的环境。

## 浏览器检查与准备

`scripts/wealth_browser_test_server.py` 必须提供名称含 test 的独立 SQLite `--database`、私有 `--control` 文件，可选 `--port`、`--advisor-history`、`--real-model`。控制文件只供本地测试注入业务时钟与故障，不是产品 HTTP 时间推进接口，不改变真实 TTL；测试 Web 使用独立端口、API 地址及构建目录。

页面检查顺序：工作台导航 → 账户／账单筛选和翻页 → 消费月份 → 报告 → 订阅 → 转账与收款 → 理财 → 通知详情。写流程分别检查核对、确认、强验证、等待、UNKNOWN 与终态；通知检查已读／删除后去重，账单检查真实成功入账与余额，不把提示当扣款。

```bash
uv run --project apps/api python scripts/demo_preflight.py
```

preflight 只读检查本地演示的初始余额、数据、版本、schema、Guard 和未收敛操作；TOTP模式还检查本人已绑定认证器。已经交易过的正常环境可能不满足初始状态检查，不能因此重置。普通运行排查见 [维护指南](operations.md)。

## 重置专用演示数据

只有明确需要重新准备干净 development／test 演示时才使用。停止所有连接目标库的 API 和 Worker，按用户清理：

```bash
docker compose stop api web
APP_ENVIRONMENT=development AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking \
  uv run --project apps/api python scripts/reset_demo_state.py \
  --user-id dev-user-001 --workers-stopped
docker compose start api web
```

reset 清理指定用户业务、对话、任务、报告、消息、相关审计及 checkpoint，保留其他用户、身份映射、个人安全额度、认证器、独立安全审计、共享目录和 schema。生产模式拒绝；它是数据清理，不是撤销付款、退费或普通升级步骤。

## 保留脚本的用途

这些脚本仍提供当前代码的维护、隔离演示或外部模型验收入口。历史数据集名称不代表旧实现；模型脚本不会因离线测试通过就自动算作已实测。

| 脚本 | 用途及限制 |
| --- | --- |
| check_docs.py | 本地链接、锚点、目录、版本、迁移和已废弃操作说明检查 |
| package_source.py | 输出源码 ZIP 与 SHA-256；排除私密配置、依赖、构建结果及视频制作资料 |
| configure_local_mfa.py | 切换后端验证模式，保留本人验证码和已有密钥，不输出凭据 |
| prepare_oidc_demo.py | 生成私有 Keycloak／TOTP 演示配置及显式用户映射；重复准备不覆盖原密钥 |
| demo_preflight.py | 只读检查专用演示的初始条件，不自动重置正常使用数据 |
| validate_mock_data.py | 校验合成数据的归属、类型及数量 |
| generate_mock_data.py | 显式重建合成银行数据，会修改提交的fixture |
| generate_golden_financial_metrics.py、generate_golden_monthly_report_core.py | 在规则确需变化时重建金融及报告黄金结果 |
| smoke_agent.py、smoke_routing.py | 外部模型基础查询、路由和受限工具调用诊断 |
| smoke_transfer_draft.py、smoke_transfer_authorization.py、smoke_transfer_operation.py | 外部模型转账草稿、确认验证及幂等执行分片检查，使用隔离环境 |
| smoke_monthly_report_skill.py | 外部模型报告草稿协议及确定性核心检查 |
| smoke_report_product.py、smoke_report_stability.py | 隔离库中的报告持久化和重复执行稳定性检查 |
| smoke_plan_product.py、smoke_plan_conditions.py | 本地独立API的查询DAG、订阅交接和显式条件检查，可能执行模拟写入 |
| smoke_audit_product.py、smoke_security_product.py | 本地独立API的授权审计与绕过拒绝检查，不连接保留业务状态的环境 |
| smoke_wealth.py | 独立PostgreSQL库中的确定性申赎及恢复闭环 |
| evaluate_wealth_v0113.py | 当前理财实现的固定表达数据集及模型正文评估，文件名关联测试集 |
| wealth_browser_test_server.py | 独立SQLite和私有控制文件的浏览器验收服务 |
| run_code_sandbox.py | 将选定分析代码发送至受限容器，输出执行摘要审计 |
| reset_demo_state.py | 仅在已停Worker的专用演示环境按用户清理；不是升级或撤销交易 |
