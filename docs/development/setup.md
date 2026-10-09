# 环境配置、本地开发与升级

## Docker 启动

仓库根目录复制 `.env.example` 为 `.env`，填写真实可用的 OpenAI-compatible `LLM_BASE_URL`、`LLM_API_KEY` 与 `LLM_MODEL`，设置自己的 `MOCK_REAUTH_CODE`。API root 不含 `/chat/completions`。

```bash
cp .env.example .env
docker compose up --build -d
```

示例明确设置 `APP_ENVIRONMENT=development`、`AUTH_MODE=development`、`NEXT_PUBLIC_AUTH_MODE=development` 和 `DEVELOPMENT_USER_ID=dev-user-001`。身份模式必须显式指定。Web 为 3000，API 为 8000，PostgreSQL 为 5432；容器 API 启动命令自动运行 Alembic。

## 关键配置

完整参数见仓库 [.env.example](../../.env.example) 和 [Settings](../../apps/api/src/banking_api/config/settings.py)。

| 参数 | 示例／默认行为 |
| --- | --- |
| `AGENT_RUNTIME` | 产品使用 `langgraph`，manual 为参考 |
| `AGENT_MAX_STEPS` / `AGENT_MAX_TOOL_CALLS` | 默认 6 / 8 |
| `BANKING_BUSINESS_TIMEZONE` | 默认 `Asia/Shanghai` |
| `TASK_WORKER_ENABLED` / `OPERATION_RECOVERY_ENABLED` / `OUTBOX_PUBLISHER_ENABLED` | 默认开启；Task heartbeat 必须小于 lease |
| `MOCK_SCHEDULED_TRANSFERS_ENABLED` | 默认关闭；开启后运行预约 Worker |
| `MOCK_SUBSCRIPTION_BILLING_ENABLED` | Settings 默认关闭，Compose 与示例默认开启；仅 development/test |
| `MOCK_PARTICIPANT_LOGIN_ENABLED` | 默认关闭，开启须 development 身份及私有签名 key ≥32 字符 |
| `SCHEDULED_TRANSFER_MIN_ADVANCE_SECONDS` / `MAX_DAYS` / `LATE_WINDOW_SECONDS` | 默认 60 秒 / 30 天 / 300 秒，完整变量名均以 `SCHEDULED_TRANSFER_` 开头 |
| `RECURRING_TRANSFER_MAX_OCCURRENCES` / `RECURRING_TRANSFER_MAX_DAYS` | 默认 12 次 / 366 天，只可在代码允许范围内收紧 |
| `TRANSFER_APPROVAL_TTL_SECONDS` / `TRANSFER_REAUTH_TTL_SECONDS` | 默认 600 / 300 秒，预约独立授权不延长 TTL |
| `LANGGRAPH_CHECKPOINT_DATABASE_URL` | 可单独指定；否则使用应用数据库 URL |
| `DEMO_REFERENCE_TIME` | 可选、带时区的 development/test 合成数据读取时间；生产拒绝 |

风险业务日、授权 TTL、租约、恢复和消息 Worker 的调度仍用真实时间。不要把 Demo 读取时钟当作全局时间冻结。

## 本地开发

需要 Python 3.12+、uv、支持前端测试的 Node.js，以及 `package.json` 指定的 pnpm 11.19.0。先准备 `.env`，启动 PostgreSQL：

```bash
docker compose up -d postgres
```

本地进程连接 `localhost`，不能沿用 `.env` 中仅容器内可解析的 `postgres` 主机名。一个终端运行后端：

```bash
cd apps/api
uv sync
export DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking
export LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking
uv run --env-file ../../.env alembic upgrade head
uv run --env-file ../../.env uvicorn banking_api.main:app --reload
```

Settings 按进程工作目录读取 `.env`；上面的 `--env-file ../../.env` 显式加载仓库根配置，环境变量仍优先。另一个终端在仓库根目录启动前端：

```bash
pnpm install
pnpm web:dev
```

前端使用 `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`。本地 Next.js 开发环境需要能读取相应的 NEXT_PUBLIC 配置，可将这些公开配置放在 `apps/web/.env.local`；不向前端复制 LLM 密钥。更新公开构建参数后，Docker Web 需要重新构建。

## OIDC 模式

设置 `AUTH_MODE=oidc`、`OIDC_ISSUER`、`OIDC_AUDIENCE`、允许签名算法，并设置前端 authority、client ID 和 scope。`OIDC_JWKS_URL` 可留空以使用 discovery。生产环境禁止 development 登录和模拟订阅扣费。

前端使用 Authorization Code + PKCE，access token 保存于内存，HTTP 和 fetch-streaming SSE 通过 Bearer header 认证。合法外部身份仍需要显式映射：

```bash
cd apps/api
uv run --env-file ../../.env python -m banking_api.security.authentication.provision \
  --user-id dev-user-001 \
  --issuer https://idp.example.com \
  --subject external-subject
```

这些实现提供 OIDC-ready 边界，当前未验收真实生产 IdP 与真实 MFA 的完整闭环。

## 升级到 v0.10.3

当前迁移 head 为 `0033`。已有环境先备份数据库、暂停新业务写入并安排未收敛操作，再同步代码与迁移。不要为升级清库或执行 Demo reset。

Docker API 启动自动迁移；手动迁移需显式配置目标 DATABASE_URL，在 `apps/api` 执行：

```bash
uv run --env-file ../../.env alembic upgrade head
```

`0031` 新增消息中心，`0032` 新增订阅提醒游标与模拟扣费账本，`0033` 更新已有提醒文案。页面内确认取消复用已有合同与动作账本。更早备注、预约、AA、移除手机号转账、周期授权和列表软删除迁移随链执行，历史编号保留。

迁移后重启 API/Web，检查 `/health` 和 [preflight](testing.md)。版本及迁移依据：[API 版本](../../apps/api/src/banking_api/__init__.py)、[迁移 0033](../../apps/api/migrations/versions/0033_renewal_reminder_copy.py)。
