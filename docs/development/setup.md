# BAVA 部署、环境配置与升级

## 环境要求

Docker 方式需要已启动的 Docker Engine／Docker Desktop 和 Docker Compose v2+，以及访问容器镜像与依赖仓库的网络。首次构建会下载镜像、Python 和 Node 依赖；不需要在宿主机单独安装 Python／Node。默认占用 3000、8000、5432 端口。自然语言功能需要部署者配置可用的 OpenAI-compatible 模型服务，源码包不携带 API key。

## Docker 启动

在仓库根目录复制 [.env.example](../../.env.example) 为 `.env`，填写可用的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 和私有 `MOCK_REAUTH_CODE`。Base URL 不含 `/chat/completions`。

```bash
cp .env.example .env
chmod 600 .env
docker compose up --build -d
docker compose ps
curl --fail http://localhost:8000/health
```

示例显式设置 `APP_ENVIRONMENT=development`、`AUTH_MODE=development`、`NEXT_PUBLIC_AUTH_MODE=development`，默认用户为 dev-user-001。Web 3000、API 8000、PostgreSQL 5432；API 启动自动执行 Alembic。

访问 [BAVA 工作台](http://localhost:3000/) 和 [API 文档](http://localhost:8000/docs)。首次账户、交易和产品使用项目合成数据；无需手工导入 SQL。用“我有哪些账户？”检查模型与工具链，再按[验收用例](../competition/acceptance.md)逐项检查。`/health` 只证明 HTTP 进程响应，模型调用是否可用以真实对话为准。

当前日期晚于合成交易数据时，可在 `.env` 中设置模板注释提供的 `DEMO_REFERENCE_TIME=2026-09-28T12:00:00Z`，便于复核近 30 天异常／续费示例；固定月份的账单查询也可直接使用 2026 年 8 月。该设置不改变授权有效期、转账业务日、租约和真实恢复调度。

仅停止服务使用 `docker compose stop`，恢复使用 `docker compose start`；删除容器使用 `docker compose down`，命名卷保留业务数据。重新构建使用 `docker compose up --build -d`。不要把删除数据库卷作为普通更新步骤。

## 远程访问与常见部署问题

浏览器通过公开 API 地址发请求。在其他设备访问时，将 `NEXT_PUBLIC_API_BASE_URL` 改为浏览器可访问的 API 地址，同时把前端地址放入 JSON 数组格式的 `CORS_ORIGINS`，例如 `CORS_ORIGINS=["http://192.168.1.20:3000"]`；改变前端构建配置后必须重建 Web。`WEB_PORT`、`API_PORT` 分别调整宿主端口映射；调整 Web 端口也要同步 CORS。

| 现象 | 处理 |
| --- | --- |
| 镜像／依赖下载失败 | 检查 Docker 已启动、网络及镜像仓库访问，再重新构建；安装使用提交的锁文件 |
| API 启动失败 | 查看 `docker compose logs --tail 100 api`，核对数据库连接、环境模式和迁移；升级已有库先备份 |
| 页面正常但对话失败 | 检查模型 base URL、key、model 和提供商可用性；base URL 不含 `/chat/completions` |
| 浏览器无法请求 API | 检查浏览器可达地址、CORS、端口映射；远程浏览器的 localhost 指向其自身设备 |

默认 development 身份面向本机合成环境；对外部署的身份配置见下文 OIDC 与[安全自评](../competition/security-assessment.md)。

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
| `REAUTH_PROVIDER` | mock仅开发／测试；totp使用本人动态码，production必须totp |
| `MFA_ENCRYPTION_KEY`／`MFA_ISSUER` | TOTP密钥加密key与认证器显示名；key必须持久、私密，不可在重启时重新生成 |
| `SUBSCRIPTION_READ_CONSENT_SECONDS` | 订阅查询确认的有效期，默认300秒 |
| `BANKING_BUSINESS_TIMEZONE` | 默认 Asia/Shanghai |
| `LANGGRAPH_CHECKPOINT_DATABASE_URL` | 可独立配置，否则复用应用数据库地址 |
| `DEMO_REFERENCE_TIME` | 可选带时区的合成数据读取参考时间，production 拒绝 |

异常通知 Worker 默认约 30 秒运行，当前没有独立环境开关；订阅 Worker 默认约 30 秒运行，扣费开关只控制模拟扣费。读取参考时间不改变风险业务日、授权 TTL、租约或恢复调度；订阅扣费使用实际 Worker 时间。

Docker 只传递 [Compose](../../docker-compose.yml) 的 environment 中声明的变量。新增或高级 Settings 参数须同步添加 Compose 透传；修改根 `.env` 并不自动把所有变量传入容器。前端 `NEXT_PUBLIC_*` 是构建配置，修改后重建 Web，不能包含 LLM 密钥。

## 本地开发

本地身份验证码仅保存在后端私密环境，金融总览提供免密额度设置；可选真实认证器后端配置见[身份验证指南](../guides/security.md)。独立代码沙箱不在API中执行，构建与验证见[沙箱](../architecture/sandbox.md)。

需要 Python 3.12+、uv、Node.js 22.15+ 和根 package.json 指定的 pnpm 11.19.0。前端测试除类型剥离外还使用 `node:module.registerHooks`，该API从22.15.0开始提供，见[Node官方说明](https://nodejs.org/api/module.html#moduleregisterhooksoptions)。先准备 `.env` 和数据库：

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

评审可直接使用[完整登录与动态码演示环境](oidc-demo.md)，一并启动独立 Keycloak，完成实际 OIDC 与 TOTP 授权闭环。以下参数用于接入自有身份服务。

设置 `AUTH_MODE=oidc`、`OIDC_ISSUER`、`OIDC_AUDIENCE` 及允许的非对称签名算法；`OIDC_JWKS_URL` 为空时使用 discovery。前端设置 OIDC authority、client ID、scope 和对应 auth mode。

前端采用 Authorization Code + PKCE，access token 仅在内存，通过 Bearer header 访问 HTTP 和 fetch-streaming SSE。外部身份须显式映射；在已正确配置数据库的后端终端执行：

```bash
uv run --env-file ../../.env python -m banking_api.security.authentication.provision \
  --user-id dev-user-001 --issuer https://idp.example.com --subject external-subject
```

生产模式拒绝 development 身份、合成读取时钟、Mock 理财和 Mock 订阅扣费。完整演示环境通过独立 Keycloak 完成 OIDC 登录与 TOTP 交易验证；接入自有身份服务时，配置其 issuer、audience、JWKS 与用户映射。金融渠道的合成／Mock 范围见[提交说明](../competition/submission.md)。

## 升级数据库

当前迁移 head 为 **0038**。已有环境先备份并暂停新写入，同步代码后按迁移链升级；不清库、不用 reset 代替迁移。

Docker API 启动自动升级。手动操作在已配置目标数据库的 `apps/api` 目录执行：

```bash
uv run --env-file ../../.env alembic current
uv run --env-file ../../.env alembic upgrade head
uv run --env-file ../../.env alembic current
```

迁移链保留历史编号和数据转换。当前 schema 包含消息／订阅扣费账本、理财资源、AA 列表软删除和异常证据快照。删除使用说明中的发布历史不意味着可以删除或改写历史迁移。

存在理财业务数据时拒绝破坏性降级；有异常通知证据时拒绝删除该快照字段。升级失败先查目标库、迁移和日志，不清空账本重试。升级后重启 API／Web 并核对版本、schema 和业务状态，见 [运行维护](operations.md)。
