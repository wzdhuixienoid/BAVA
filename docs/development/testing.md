# 测试、数据校验与演示

本文给出当前验证方法，不报告本次文档整理期间未执行的业务测试结果。历史测试数量见 [档案](../archive/README.md)。

## 常用检查

在仓库根目录执行：

```bash
uv run --project apps/api ruff check apps/api scripts
uv run --project apps/api pytest apps/api/tests -m 'not postgres'
pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm --filter @banking/web test
pnpm web:build
```

`api:generate` 从 `packages/api-client` 的生成脚本读取运行中的 API OpenAPI。调用前先启动当前 API；生成文件变化需要一并检查。

PostgreSQL 测试需要库名包含 `test` 的独立数据库，测试会清理该库数据。首次运行先建库、迁移，再执行：

```bash
# 仓库根目录，数据库不存在时执行一次

docker compose exec -T postgres createdb -U banking banking_docs_test
```

```bash
cd apps/api
APP_ENVIRONMENT=test AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_docs_test \
  uv run alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_docs_test \
  uv run pytest -m postgres
```

不要与连接同一测试库的 API 或 Worker 并行运行。SQLite 测试不能替代 PostgreSQL 锁、lease 与唯一约束的并发验证。

## 模拟数据与黄金结果

在仓库根目录、Python 3.12 环境运行：

```bash
uv run --project apps/api python scripts/generate_mock_data.py
uv run --project apps/api python scripts/generate_golden_financial_metrics.py
uv run --project apps/api python scripts/validate_mock_data.py
```

再生成会修改提交的 fixture 和黄金结果，需要检查差异，不能为了通过测试随意重写预期。另有 `generate_golden_monthly_report_core.py` 生成报告核心黄金数据。API 重启后读取更新的 fixture；无须清空业务数据库。

## Smoke 的执行边界

`scripts/smoke_report_product.py` 和 `smoke_report_stability.py` 自行驱动 TaskRunner，需要已迁移的独立测试数据库与配置模型。同一库不同时运行 API worker。稳定性默认按显式次数运行，示例：

```bash
APP_ENVIRONMENT=test AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_docs_test \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking_docs_test \
  uv run --project apps/api python scripts/smoke_report_stability.py --runs 10
```

真实模型 Smoke 有调用费用，向配置的模型服务提供必要合成汇总；通过次数只是有限测试证据。HTTP Plan／Audit／Security Smoke 使用独立 API，支持 `PLAN_SMOKE_BASE_URL`、`AUDIT_SMOKE_BASE_URL`、`SECURITY_SMOKE_BASE_URL` 指向如 `http://127.0.0.1:8001`。这些脚本可能创建模拟转账、取消合同或触发安全控制，不要指向保留演示状态的数据库。

## 演示准备与页面检查

运行产品后先在仓库根目录检查：

```bash
uv run --project apps/api python scripts/demo_preflight.py
```

preflight 是只读检查，核对版本、迁移、初始数据、Guard、Mock 模式与未收敛操作；不能替代所有页面和模型输入验收。

建议依次检查账户 → 消费 → 报告 → 订阅 → 转账 → 预约／AA → 安全控制。每个写流程分别检查核对、确认、强验证、等待和终态，不把 Task 完成当付款成功。消息测试需查看提醒、已读和删除后的去重，模拟扣费须另检查账本和余额。

当前页面预期见 [财务指南](../guides/financial-analysis.md)、[转账指南](../guides/transfers.md)、[订阅指南](../guides/subscriptions.md)。历史网页教程中的黄色小额转账规则已经失效。

## 重置演示数据

仅在需要重新准备干净的 development/test 演示时使用。先停止所有连接目标库的 API 与 Worker，再显式按用户清理：

```bash
docker compose stop api web
APP_ENVIRONMENT=development AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking \
  uv run --project apps/api python scripts/reset_demo_state.py \
  --user-id dev-user-001 --workers-stopped
docker compose start api web
```

reset 清理该用户的演示业务、对话、任务、报告、消息及相关审计与 checkpoint；保留其他用户、身份映射和 schema。它是数据清理，不是撤销付款或订阅扣费。生产环境在连接数据库前拒绝。重启后重新运行 preflight。
