# Test Results v0.7.1

执行日期：2026-09-28（Asia/Shanghai）

## 1. 定向开发测试

风险与 Transfer 定向批次最终结果：

```text
28 passed in 2.19s
```

新增覆盖包括：

- R1 read-only -> GREEN；
- `1000.00` YELLOW / `1000.01` RED 的 Decimal 边界；
- YELLOW Approval 后直接 `READY_FOR_COMMIT`，Reauthentication count 为 0；
- RED Approval 后 `REAUTH_REQUIRED`，无 Reauthentication 时不创建 Operation；
- RED 正常 Approval -> Reauthentication -> Operation 链路；
- review YELLOW，commit-time exposure 变化后升级 RED，保留 Approval，Operation count 为 0；
- payload 从 500 改为 1500 后 Approval/Reauthentication 失效且重评估为 RED；
- `CREATED / SUBMITTED / UNKNOWN` in-flight exposure，`FAILED` 排除；
- Provider success 与 Application in-flight 按 idempotency key 去重；
- `Principal.user_id` 隔离和 Asia/Shanghai 跨日边界；
- Prompt Injection 不能写入或降低 risk/control fields；
- risk Event 与 Outbox 原子持久化。

## 2. 最终 backend regression

```bash
cd apps/api
uv run ruff check . ../../scripts
uv run pytest -q
```

结果：

```text
All checks passed!
226 passed, 21 skipped in 6.55s
```

21 个 skip 是该命令未提供 `TEST_DATABASE_URL` 的 PostgreSQL marker，随后单独执行。

## 3. PostgreSQL suite

当地 `banking_test` 初始停留在 Alembic `0012`，第一次环境检查因缺少 `0013` 的 `identity_mappings` 和 provider `user_id` 而无法进入用例。对这个明确的隔离测试库执行现有 migration：

```bash
DATABASE_URL=postgresql+asyncpg://banking:***@localhost:5432/banking_test \
AUTH_MODE=development APP_ENVIRONMENT=test \
  uv run alembic upgrade head
```

结果：`0012 -> 0013` 成功。本版没有新增 migration。

有效的最终 PostgreSQL suite：

```bash
TEST_DATABASE_URL=postgresql+asyncpg://banking:***@localhost:5432/banking_test \
  uv run pytest -q -m postgres
```

结果：

```text
22 passed, 225 deselected in 3.10s
```

新的真实 PostgreSQL 并发用例使两个独立 session 同时 commit 同一用户的两个 600 元 YELLOW Workflow。结果只有一个 Operation 进入 `COMMITTING`，另一个在新鲜 in-flight exposure 下升级为 RED / `REAUTH_REQUIRED`。

## 4. OpenAPI 与 Web

```bash
pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

结果：全部通过。Next.js 15.5.2 production build 成功生成 `/`、`/auth/popup-callback`、`/reports` 和 `/reports/[reportId]`。

## 5. 产品链路结果

- YELLOW：当日 0 + 本笔 500 -> YELLOW -> Approval -> `READY_FOR_COMMIT` -> Operation `SUCCEEDED`；Reauthentication count = 0。
- RED：当日 800 + 本笔 200.01 -> RED -> Approval -> `REAUTH_REQUIRED`；未强验证时 Operation count = 0。现有 RED 端到端用例验证完成 Mock Reauthentication 后才可创建并执行 Operation。

本版没有重做 v0.5.x crash/restart product smoke；相关 regression 保留在完整 backend/PostgreSQL suite 中。
