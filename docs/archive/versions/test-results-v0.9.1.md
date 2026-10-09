# 历史档案：Test Results v0.9.1

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

测试日期：2026-10-02。版本：0.9.1。以下状态仅使用 PASS / FAIL / NOT RUN；计数仅来自实际工具输出。非测试命令不提供 passed/failed/skipped 计数，记为 N/A，不伪造 duration。

## 环境

- macOS 本地 workspace；Python 3.12.7、pytest 8.4.2；Node 24.20.0、pnpm 11.19.0、Next.js 15.5.2。
- Docker PostgreSQL 17-alpine、API Python 3.12、Web Node 22-alpine。
- 后端 full suite 使用测试 fixture；PostgreSQL 使用明确隔离库 `banking_release_v091_test`（名称含 test）。应用 Demo 使用本地 `banking` synthetic 环境，没有真实银行或真实业务数据。
- 真实 LLM smoke 使用配置的 OpenAI-compatible endpoint `api.deepseek.com`、model `deepseek-v4-flash`；不记录密钥或隐藏推理。
- PostgreSQL destructive test fixtures 不应与该库的 API/worker 同时运行；Plan HTTP smoke 服务只在 smoke 期间运行，结束即停止。
- 本机 pnpm 的自动 verify-deps-before-run 在无 TTY 下曾报 `ERR_PNPM_ABORTED_REMOVE_MODULES_DIR_NO_TTY`。使用 `CI=true pnpm install --offline --ignore-scripts` 准备已有依赖，再以 `pnpm_config_verify_deps_before_run=false` 执行下面所有 pnpm 命令；未修改项目依赖或全局配置。

## Backend

工作目录：`apps/api`。

| Status | 实际 command | Exit | Passed | Failed | Skipped | Warnings |
|---|---|---:|---:|---:|---:|---|
| PASS | `uv run ruff check . ../../scripts` | 0 | N/A | N/A | N/A | 输出 All checks passed，未报告 warning |
| PASS | `uv run pytest` | 0 | 503 | 0 | 35 | 未报告 warning summary |
| PASS | `TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_release_v091_test uv run pytest -m postgres` | 0 | 36 | 0 | 0 | 502 deselected，未报告 warning summary |
| PASS | `TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_release_v091_test uv run pytest tests/test_demo_reset.py -q` | 0 | 5 | 0 | 0 | 未报告 warning summary |
| PASS | `DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_release_v091_test uv run alembic upgrade head` | 0 | N/A | N/A | N/A | 0001→0017，未报告 warning |
| PASS | `uv run alembic heads` | 0 | N/A | N/A | N/A | `0017 (head)` |

Full suite 的 35 skipped 为未设置 TEST_DATABASE_URL 时的 PostgreSQL 场景，已由专项命令实际运行。两次 suite 有一个无需 DB 的 marked case 重叠，不能简单相加计为唯一测试总数。最后 pytest 输出 duration：14.84s；PostgreSQL：6.98s。

既有覆盖包括账户、金融统计/报告 golden、四种异常规则、订阅检测/取消/幂等、YELLOW/RED/exposure/commit 升级、Approval hash/expiry/mutation、reauth TTL/attempt、guard、Operation CREATED/SUBMITTED/UNKNOWN recovery/idempotency、provider 余额/并发保护、Plan/DAG/条件 grounding/takeover/resume/rollback、ownership、Task claim/lease/fencing、Outbox。

新增后端文件：`test_authoritative_accounts.py`（7 cases）、`test_transfer_currency_policy.py`（8 cases）、`test_product_projections.py`（3 cases）、`test_demo_reset.py`（5 cases，含 PostgreSQL）。既有 `test_agent_task_e2e.py` 和 `test_postgres_integration.py` 增加 authoritative account output 断言；`test_subscriptions.py` 补充 managed / detected-only 候选的后端 cancellable 断言。

## Frontend

工作目录：repository root。表内 pnpm command 均带上述环境前缀。

| Status | 实际 command | Exit | Passed | Failed | Skipped | Warnings |
|---|---|---:|---:|---:|---:|---|
| PASS | `pnpm api:generate` | 0 | N/A | N/A | N/A | 从 Docker API `http://localhost:8000/openapi.json` 生成，未报告 warning |
| PASS | `pnpm web:lint` | 0 | N/A | N/A | N/A | 未报告 warning |
| PASS | `pnpm web:typecheck` | 0 | N/A | N/A | N/A | 未报告 warning |
| PASS | `pnpm --filter @banking/web test` | 0 | 20 | 0 | 0 | 3 条 Node MODULE_TYPELESS_PACKAGE_JSON warning；非失败 |
| PASS | `pnpm web:build` | 0 | N/A | N/A | N/A | production build 完成、8 static pages；未报告 warning |

最终测试工具 duration_ms：401.348167。源码最后变化后的 build 输出 Compiled successfully in 1614ms；不将编译耗时当作整个 build duration。

新增行为覆盖：真实 AccountResults / AssistantTurn 在错误 LLM prose 下仍展示 23864.52 后端余额；600 元 + backend RED/exposure；FALSE 不由浏览器比较（另构造 actual 5000 > threshold 4000 仍后端 FALSE）；UNKNOWN 没有成功回执和完成索引；Task COMPLETED + READY_FOR_REVIEW 没有业务成功；真实 DAG/Guard/SKIPPED；DETECTED_ONLY 无执行取消，包含仅供引用的非空 subscription_id 候选；所有主要中文状态与安全拒绝错误展示。既有 8 个 conversation timeline tests 保持通过。

最后候选项行为测试强化时，typecheck 曾以 exit 2 报 DTO 缺少 cancellable；已从现有 SubscriptionItem 直接传递该字段、缺省 false，并重新生成 OpenAPI。最终上述完整前端命令均 exit 0。一次沙箱内 api:generate 以 exit 1 / localhost EPERM 拒绝连接，使用获准本地网络环境重跑成功，未更改 API schema 以绕过检查。

## Runtime / Docker

| Status | 实际 command / check | Exit | Passed / Failed / Skipped | Warnings / evidence |
|---|---|---:|---|---|
| PASS | `docker compose down` | 0 | N/A / N/A / N/A | 未删除 volume |
| PASS | `docker compose up --build -d` | 0 | N/A / N/A / N/A | 初次 dependency 下载曾重试，最终构建启动成功 |
| PASS | `docker compose up --build -d api web`、最终 `docker compose up --build -d` | 0 | N/A / N/A / N/A | 最终 API 与 Web 镜像构建成功 |
| PASS | `docker compose ps` | 0 | N/A / N/A / N/A | PostgreSQL healthy；API、Web Up |
| PASS | GET `/openapi.json` | 0 | N/A / N/A / N/A | info.version = 0.9.1 |
| PASS | 显式用户范围 Demo reset CLI，重复及验收结束后恢复 | 0 | N/A / N/A / N/A | 初始余额 23864.52、零 exposure、订阅 ACTIVE、guard NORMAL；保留 schema/migration |
| PASS | `git diff --check` | 0 | N/A / N/A / N/A | 无 whitespace error |

一次 Docker registry metadata 请求以 exit 1 / ghcr.io TLS handshake timeout 失败；随后 API 和全产品构建重跑均 exit 0，没有修改 TLS 或镜像来源。

Reset 实际命令：

```bash
docker compose stop api web
APP_ENVIRONMENT=development AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking \
  uv run --project apps/api python scripts/reset_demo_state.py \
  --user-id dev-user-001 --workers-stopped
docker compose start api web
```

首次 reset 清理 390 checkpoint writes / 165 blobs / 81 checkpoints、405 Events/Outbox，以及该用户工作流、任务、ledger 等。重复执行各项清理数量为 0。后续真实转账、计划、订阅、guard 验收后再次 reset 成功，最终 Dashboard 工资卡为 ¥23,864.52。最后一次清理 24 checkpoint writes / 10 blobs / 5 checkpoints、35 Events/Outbox、1 Report / 1 Task / 1 Conversation / 2 Messages；紧接着重复清理各项均为 0。只读 SQL 确认 transfer/subscription ledger、Operation、Workflow 为 0，Alembic 仍为 0017；资源 API 确认订阅 ACTIVE、guard NORMAL。

## Product smoke

报告 smoke 与 Plan smoke 使用隔离 synthetic test DB。报告脚本自行运行 TaskRunner，不与该库的 API worker 同时执行；Plan 脚本通过独立 API 的真实 HTTP worker 执行。

```bash
APP_ENVIRONMENT=test AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_release_v091_test \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking_release_v091_test \
  uv run --project apps/api python scripts/smoke_report_product.py
```

```bash
# 独立 terminal，Plan smoke 完成后停止该服务
APP_ENVIRONMENT=test AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_release_v091_test \
LANGGRAPH_CHECKPOINT_DATABASE_URL=postgresql://banking:banking@localhost:5432/banking_release_v091_test \
  uv run --project apps/api uvicorn banking_api.main:app --host 127.0.0.1 --port 8001
APP_ENVIRONMENT=test AUTH_MODE=development PLAN_SMOKE_BASE_URL=http://127.0.0.1:8001 \
  uv run --project apps/api python scripts/smoke_plan_product.py
```

| Status | Command | Exit | Passed / Failed / Skipped | Warnings / evidence |
|---|---|---:|---|---|
| PASS | 初次 report product smoke | 0 | N/A / N/A / N/A | Router、四个 Tools、Skill、Report GET、golden_core_equal=true、单一确认消息；支出 16547.30、环比 +77.3% |
| FAIL | report product smoke（提示修正前的重跑） | 1 | N/A / N/A / N/A | REPORT_NARRATIVE_VALIDATION_FAILED，保留既有拒绝校验 |
| PASS | 最终 report product smoke（明确禁字符的提示后） | 0 | N/A / N/A / N/A | 四个金融 Tools、Report GET、golden_core_equal=true、16547.30 CNY / +77.3%、单一确认消息；未报告 warning |
| PASS | 最终 plan product smoke（含 candidate DTO 更新后重跑） | 0 | N/A / N/A / N/A | 2 bounded read outputs，Plan/Task COMPLETED；写步骤 WAITING_USER/YELLOW、0 Operation/no reauth；显式 approve/commit 后同一个 Operation 与 Workflow/Step/Plan/Task SUCCEEDED |

一次 PostgreSQL suite 重跑时临时 smoke API 尚未停止，worker 日志出现 lease lost/fenced（测试 fixture 改动该隔离库）；已停止旧 API 并在 suite 完成后单独重跑 Plan smoke，通过。最终不保留该临时 API，亦不在 fixture 测试期间运行该库 worker。

单独报告诊断也通过。为降低报告文字误触既有数字禁用规则的机会，只明确 Prompt 禁字符及“之一/第一/进一步”等措辞；没有改变 SkillExecutor 校验、重试次数、core 或报告成功条件。一次提示编辑 lint 曾发现 E501 行长，分行后最终 ruff 与 full pytest 通过。

## Browser acceptance

使用真实 in-app browser 操作本地 Docker 产品，非 unit test 推测。Desktop 1440×900；Mobile 390×844。表内结果是最终实际验收，初次拒绝及修正列在备注。

| Case | Status | 实际 evidence |
|---|---|---|
| T1 Accounts | PASS | “我有哪些账户？”和“工资卡余额多少？”展示 masked number、CNY、账户类型、服务器 as_of 和 ledger 后真实余额；reset 后 Dashboard 工资卡 23864.52 |
| T2 Financial Analysis | PASS | 2026-08 总支出 16547.30、收入 23800、上月 9333.20、绝对变化 7214.10、+77.3%、分类分布；Dashboard Top 5 完整，未由前端聚合 |
| T3 Monthly Report | PASS | 报告卡、完成索引、打开详情；数值与 Dashboard/golden 一致。初次 LLM narrative 校验拒绝，重新生成后通过，未放宽校验 |
| T4 Subscription | PASS | 每项月度/年度成本、可管理/仅检测、当前状态、涨价证据、续费；晨光健身 DETECTED_ONLY 无取消入口 |
| T5 Anomaly | PASS | 实际 AMOUNT_SPIKE 高/中 severity、商户/金额/时间、baseline/ratio/count evidence，明确非已确认欺诈 |
| T6 YELLOW Transfer | PASS | reset 后 500 元，收款人/账户确认，YELLOW、Approval、commit、双 SUCCEEDED、Provider reference、完成索引 1 |
| T7 RED Transfer | PASS | reset 后 2000 元，RED、Approval、Mock reauth、commit、双 SUCCEEDED。模拟验证码以当前 .env 配置为准 |
| T8 Exposure escalation | PASS | 本笔 600 元、当日成功 2000、projected exposure 2600、阈值 1000，UI 仍 RED；草稿取消无额外扣款 |
| T9 Condition TRUE | PASS | 原始 3000/500 中文请求；actual 21864.52、threshold 3000、TRUE、真实 DAG/Guard、工作流仍等待 Approval。初次 currency 提取为“元”安全拒绝，字段说明修正后同一请求通过 |
| T10 Condition FALSE | PASS | threshold 50000、actual 21864.52、FALSE，写 Step SKIPPED、完成索引 0；资源 API workflows=[] |
| T11 Subscription Cancellation | PASS | 星幕视频 YELLOW、Approval、commit、双 SUCCEEDED；订阅总览已取消、月度/年度成本 0、无下次续费 |
| T12 UNKNOWN | PASS | 既有 TIMEOUT_AFTER_ACCEPT 故障 Provider 经真实 Domain Service 得到 UNKNOWN；延后自动 due time 便于观察。Task 人为 COMPLETED 但 UI 无成功回执、索引 0；点击检查状态 reconcile 原 Operation 后双 SUCCEEDED、索引 1 |
| T13 Security Guard | PASS | 最后进行：三次真实 Mock 验证失败触发 WRITE_LOCKED；GREEN 余额查询正常；新取消 commit 返回 423，Approval 仍 APPROVED、operation_summary=null、订阅仍 ACTIVE |
| T14 Responsive | PASS | 两个指定尺寸实际检查 Dashboard、DAG、Condition、Workflow；document.scrollWidth 分别等于 1440/390；底部输入可填、移动完成索引可切换并定位回执，无整页横向溢出 |

UNKNOWN 场景使用临时本地测试 harness 复用既有测试 helper、OperationService 与 Mock Provider，未新增 fault injection 业务 API/Tool，未伪造 SUCCEEDED。延迟 next_reconcile_at 仅控制测试观察时机，最终由 Provider ledger reconcile 确认。

构建重启期间一次浏览器 commit 出现短暂网络失败；服务恢复后刷新同一资源、重新执行，服务器按 WRITE_LOCKED 拒绝，未新增 Operation。

## Security Regression

| Invariant | Status | 实际 coverage / evidence |
|---|---|---|
| CNY-only | PASS | test_transfer_currency_policy + test_transfer_risk |
| USD account + USD fail closed | PASS | 人为 USD account / 500 USD，同币种也返回 TRANSFER_RISK_CURRENCY_UNSUPPORTED；各写边界无副作用 |
| CNY account + USD CURRENCY_MISMATCH | PASS | 既有业务校验保留；零 Operation / ledger |
| wrong LLM balance prose | PASS | fake model 写 1 元，Task/API typed result 仍 23864.52 CNY |
| authoritative balance rendering | PASS | 真实 AssistantTurn / AccountResults 自动行为测试 + T1 |
| post-transfer balance | PASS | ledger debit 后 authoritative balance 回归；T13 实际查询 23364.52 |
| YELLOW → RED exposure escalation | PASS | 后端 commit-time escalation tests、600/RED 前端测试、T8 |
| UNKNOWN != success | PASS | 前端真实 card/receipt/index 自动测试 + T12 |
| Task COMPLETED != business success | PASS | pending Workflow 自动测试 + T12 completed Task fixture |
| Approval mutation/expiry/binding | PASS | test_transfer_authorization / test_transfer_risk / PostgreSQL |
| Reauthentication | PASS | TTL/attempt/mutation regression、T7/T13 |
| WRITE_LOCKED | PASS | 后端 guard/isolation tests、T13 423 / approval unconsumed / no Operation |
| ownership isolation | PASS | test_authentication / test_principal_isolation / authoritative accounts / Dashboard owner scope |
| Condition FALSE zero write side effect | PASS | test_plan_conditions / postgres + T10 workflows=[] |
| Provider idempotency/concurrent funds | PASS | transfer operations / provider concurrency / PostgreSQL |
| Task/Operation/Outbox durability | PASS | full backend + PostgreSQL suites，lease/fencing/recovery 场景 |
| dev/test-only reset | PASS | production、未停止 worker、active lease 拒绝；other owner/schema/checkpoint migrations 保留；真实 CLI 幂等 |

## 发布核对

Migration added: no。Alembic head: 0017。只有三个新版本交付文档，旧版本文档和历史 migrations 未改动。README 当前版本/当前交付文档与 runtime/package metadata 为 0.9.1。

Release verdict：**READY**。全部验收后 Demo 已恢复初始状态；未执行生产部署或远端发布。
