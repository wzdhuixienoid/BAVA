# 环境配置与升级

## Docker 启动

在仓库根目录复制 [.env.example](../../.env.example) 为 `.env`，填写可用的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 和私有 `MOCK_REAUTH_CODE`。Base URL 不含 `/chat/completions`。

```bash
cp .env.example .env
docker compose up --build -d
```

示例显式设置 `APP_ENVIRONMENT=development`、`AUTH_MODE=development`、`NEXT_PUBLIC_AUTH_MODE=development`，默认用户为 dev-user-001。Web 3000、API 8000、PostgreSQL 5432；API 启动自动执行 Alembic。

## 关键配置

参数及校验以 [Settings](../../apps/api/src/banking_api/config/settings.py) 为准。`.env.example` 是 Docker 演示配置，不能把它与 Settings 的默认值混同。

| 参数 | 当前行为 |
| --- | --- |
| `AGENT_RUNTIME` | 默认 langgraph；manual 为参考，消费和理财产品路径固定 LangGraph |
| `AGENT_MAX_STEPS`／`AGENT_MAX_TOOL_CALLS` | 默认 6／8 |
| `TASK_WORKER_ENABLED`／`OPERATION_RECOVERY_ENABLED`／`OUTBOX_PUBLISHER_ENABLED` | 默认开启；Task heartbeat 必须小于 lease |
| `MOCK_SCHEDULED_TRANSFERS_ENABLED` | 默认关闭，开启才运行预约 Worker |
| `MOCK_SUBSCRIPTION_BILLING_ENABLED`／`MOCK_WEALTH_ENABLED` | Settings 默认关闭，Compose 示例开启；production 拒绝开启 |
| `MOCK_PARTICIPANT_LOGIN_ENABLED` | 默认关闭；仅非生产 development 身份可启用，私有签名 key 至少 32 字符；AA 页面不提供身份切换 UI |
| `SCHEDULED_TRANSFER_MIN_ADVANCE_SECONDS`／`SCHEDULED_TRANSFER_MAX_DAYS`／`SCHEDULED_TRANSFER_LATE_WINDOW_SECONDS` | 默认 60 秒／30 天／300 秒 |
| `RECURRING_TRANSFER_MAX_OCCURRENCES`／`RECURRING_TRANSFER_MAX_DAYS` | 默认 12 次／366 天，只可在代码范围内收紧 |
| `TRANSFER_APPROVAL_TTL_SECONDS`／`TRANSFER_REAUTH_TTL_SECONDS` | 默认 600／300 秒，预约使用独立授权 |
| `BANKING_BUSINESS_TIMEZONE` | 默认 Asia/Shanghai |
| `LANGGRAPH_CHECKPOINT_DATABASE_URL` | 可独立配置，否则复用应用数据库地址 |
| `DEMO_REFERENCE_TIME` | 可选带时区的合成数据读取参考时间，production 拒绝 |

异常通知 Worker 默认约 30 秒运行，当前没有独立环境开关；订阅 Worker 默认约 30 秒运行，扣费开关只控制模拟扣费。读取参考时间不改变风险业务日、授权 TTL、租约或恢复调度；订阅扣费使用实际 Worker 时间。

Docker 只传递 [Compose](../../docker-compose.yml) 的 environment 中声明的变量。新增或高级 Settings 参数须同步添加 Compose 透传；修改根 `.env` 并不自动把所有变量传入容器。前端 `NEXT_PUBLIC_*` 是构建配置，修改后重建 Web，不能包含 LLM 密钥。

## 本地开发

需要 Python 3.12+、uv、支持 `--experimental-strip-types` 的 Node.js 22.6+ 和根 package.json 指定的 pnpm 11.19.0。先准备 `.env` 和数据库：

```bash
docker compose up -d postgres
```

本地进程使用 localhost，不能使用仅容器内解析的 postgres 主机名。后端终端执行：

```bash
cd apps/api
uv sync
export DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking
export LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking
uv run --env-file ../../.env alembic upgrade head
uv run --env-file ../../.env uvicorn banking_api.main:app --reload
```

Settings 相对进程目录读取 `.env`；这里显式加载根文件，进程环境变量优先。另一个终端在根目录执行：

```bash
pnpm install
pnpm web:dev
```

在 `apps/web/.env.local` 放置前端公开配置，例如 `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`、`NEXT_PUBLIC_AUTH_MODE=development`；不要复制后端私密配置。非 3000 端口的前端还须在后端 CORS origins 中显式允许。

## OIDC

设置 `AUTH_MODE=oidc`、`OIDC_ISSUER`、`OIDC_AUDIENCE` 及允许的非对称签名算法；`OIDC_JWKS_URL` 为空时使用 discovery。前端设置 OIDC authority、client ID、scope 和对应 auth mode。

前端采用 Authorization Code + PKCE，access token 仅在内存，通过 Bearer header 访问 HTTP 和 fetch-streaming SSE。外部身份须显式映射；在已正确配置数据库的后端终端执行：

```bash
uv run --env-file ../../.env python -m banking_api.security.authentication.provision \
  --user-id dev-user-001 --issuer https://idp.example.com --subject external-subject
```

生产模式拒绝 development 身份、合成读取时钟、Mock 理财和 Mock 订阅扣费；设置 production 本身不代表已接入真实金融渠道。真实 IdP／MFA 的完整验收尚未完成。

## 升级数据库

当前迁移 head 为 **0036**。已有环境先备份并暂停新写入，同步代码后按迁移链升级；不清库、不用 reset 代替迁移。

Docker API 启动自动升级。手动操作在已配置目标数据库的 `apps/api` 目录执行：

```bash
uv run --env-file ../../.env alembic current
uv run --env-file ../../.env alembic upgrade head
uv run --env-file ../../.env alembic current
```

迁移链保留历史编号和数据转换。当前 schema 包含消息／订阅扣费账本、理财资源、AA 列表软删除和异常证据快照。删除使用说明中的发布历史不意味着可以删除或改写历史迁移。

存在理财业务数据时拒绝破坏性降级；有异常通知证据时拒绝删除该快照字段。升级失败先查目标库、迁移和日志，不清空账本重试。升级后重启 API／Web 并核对版本、schema 和业务状态，见 [运行维护](operations.md)。
