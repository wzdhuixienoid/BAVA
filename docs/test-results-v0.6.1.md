# Test Results v0.6.1

执行日期：2026-09-28（Asia/Shanghai）

## 1. Authentication and isolation coverage

新增和扩展的测试覆盖：

- 本地 RSA/JWKS valid token；
- missing token、bad signature、expired、future `nbf`、wrong issuer、wrong audience、unsupported algorithm；
- unknown `kid` 后 JWKS refresh；
- known `(issuer, subject)` 映射与 `IDENTITY_NOT_PROVISIONED`；
- 同一 subject 的 issuer namespace 隔离；
- production + development auth fail closed；
- Conversation、Task、Event、Report、Workflow、Operation detail/action 的跨用户 404；
- SSE ownership；
- Account、Balance、Payee、Financial analytics 的 Principal scope；
- Tool argument 中注入 `user_id` 不能改变 authority；
- durable Task 使用持久化 `user_id`，Task/Event 中不保存 Bearer credential；
- provider ledger/status 查询按 user scope；
- Approval 与 Reauthentication 仍作为独立 Transfer authorization boundary。

开发中的认证/隔离定向批次最终由完整 backend regression 覆盖。一次 provider advisory-lock 稳定值断言提示不能更改 v0.5.2 lock identity；实现随即保留原 lock key，并只在查询、余额和 ledger 层增加 user scope。

## 2. Backend full regression

```bash
cd apps/api
.venv/bin/pytest -q
```

结果：

```text
217 passed, 20 skipped in 6.39s
```

20 个 skip 是未向该命令提供 `TEST_DATABASE_URL` 的 PostgreSQL-marked cases；这些测试随后使用独立 PostgreSQL 17 容器单独执行。

Backend lint：

```bash
cd apps/api
.venv/bin/ruff check . ../../scripts
```

结果：`All checks passed!`

额外执行的 `ruff format --check . ../../scripts` 报告 46 个既有文件不符合当前 formatter 输出。为避免 v0.6.1 对 0.5.x reliability 代码产生大范围纯格式 diff，本版没有批量重写这些无关文件；这不是 lint 或测试失败，也不影响本版功能。

## 3. PostgreSQL migration and suite

使用独立临时 `postgres:17-alpine` 容器和库名 `banking_test`，先执行：

```bash
DATABASE_URL=postgresql+asyncpg://banking:***@localhost:55432/banking_test \
AUTH_MODE=development APP_ENVIRONMENT=test \
  .venv/bin/alembic upgrade head
```

结果：migration `0001` 到 `0013` 全部成功，head 为 `0013`。

首次 PostgreSQL suite 暴露 8 个旧测试适配问题：bank test doubles 尚未接受 `user_id`，且一个旧并发用例用两个不同用户共享同一余额。实现未回退用户隔离；测试改为同一用户下两个 Operation，并让 doubles 显式接收 user scope。

修复后的定向结果：

```text
9 passed in 1.25s
```

最终完整 PostgreSQL suite：

```bash
TEST_DATABASE_URL=postgresql+asyncpg://banking:***@localhost:55432/banking_test \
AUTH_MODE=development APP_ENVIRONMENT=test \
  .venv/bin/pytest -q -m postgres
```

结果：

```text
21 passed, 216 deselected in 2.63s
```

临时 PostgreSQL 容器在验证后已停止并自动删除。

## 4. Frontend

```bash
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

结果：三项全部通过。Next.js 15.5.2 production build 成功生成 `/`、`/auth/popup-callback`、`/reports` 和 `/reports/[reportId]`。

## 5. Isolated Docker smoke

为避免修改已运行多日的现有 compose stack 和持久卷，本次使用独立镜像、容器名、测试数据库和端口：

- API image build：通过，镜像内 `banking-api==0.6.1`；
- Web image build：通过；
- API startup：Alembic head 确认后 Uvicorn startup complete；
- `GET /health`：`200 {"status":"ok"}`；
- development auth 下 `GET /api/v1/conversations`：`200 []`；
- Web production server 首页：200，包含“银行助理工作台”；
- 本次创建的 API、Web、PostgreSQL 临时容器均已停止并自动删除；
- 现有 compose stack 未重建、未重启、未迁移。

## 6. External OIDC smoke

真实外部 OIDC 登录：**未执行**。环境没有提供真实 IdP authority/client/credential。本版完成的是 provider-neutral、production-capable OIDC/JWT protocol implementation；backend integration 使用本地 signing key、JWKS fixture 和无外网 HTTP transport。

因此没有宣称任何特定身份提供商已经上线。真实 IdP 环境仍需验证登录 → 创建 Conversation → 消息/Task 完成 → 读取自己的资源 → 登出。
