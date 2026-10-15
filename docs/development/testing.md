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

## 理财隔离Smoke

先准备库名含`test`的独立PostgreSQL库并迁移至0034，不允许连接保留演示状态的库，也不要与同库API/Worker并行。

Smoke 与回归测试使用两个独立库：Smoke 保留其新建用户和金融结果，回归测试会清理自己的测试数据。不要将 Smoke 结果带入需要验证空库降级的迁移回归；有理财业务数据时拒绝降级是预期保护。

```bash
APP_ENVIRONMENT=test AUTH_MODE=development MOCK_WEALTH_ENABLED=true \
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_wealth_test \
  uv run --project apps/api python scripts/smoke_wealth.py
```

脚本新建独立用户，不重置库，使用仅脚本内注入的时钟完成测评、推荐、对比、双重授权、申购受理/占用、受理后超时原订单恢复、成交、部分赎回成交和到账。金融结果通过确定性断言验证，不需要模型。产品没有推进时间接口，真实授权TTL、安全规则和其他业务时钟不被改动。

新增单元/API测试`test_wealth.py`，PostgreSQL测试`test_wealth_postgres.py`。后者验证账户锁同时竞争申购/转账/订阅、并发申购和并发赎回、重复到账与资金守恒。SQLite可创建完整模型；不能代替PostgreSQL并发验证。owner-scopedreset按账本/占用/订单/持仓/测评先于旧业务资源顺序删除，仅清理所选用户，保留共享目录、净值、文档和其他用户。

## v0.11.1 理财回归与浏览器验收

`test_wealth_repairs.py`覆盖暂停后重新装配、未知恢复、首次受理关闭、数量单位、全部赎回快照、本次需求否定约束、HTTP/Agent一致性和订单说明。`wealth-interaction.test.mjs`使用真实React组件事件、状态与Effect测试交互，使用匹配React版本的react-test-renderer；它不是浏览器端到端验收。

`scripts/smoke_wealth.py`另验证申购UNKNOWN和赎回受理后关闭开关、重装应用并完成原订单。浏览器验收可使用`scripts/wealth_browser_test_server.py`，必须指定文件名含test的独立SQLite库与测试控制文件，且在另一个端口使用指向该API的测试Web构建。私有控制文件内容为`{"now":"2026-10-09T09:00:00+08:00","enabled":true,"fault_mode":"SUCCESS"}`；更改文件注入业务时钟或重装测试应用，既不提供HTTP推进时间接口，也不修改产品授权TTL或安全保护规则。正式页面不得指向测试控制工具。测试端口关闭后保留验收库供核对，不重置演示库。

## v0.11.2 顾问验证

新增 test_wealth_advisory.py、wealth-analysis-interaction.test.mjs 和 PostgreSQL 快照隔离测试。检索 gold 位于 knowledge/content/wealth_retrieval_gold.json，维护方式见 [知识维护说明](../../apps/api/src/banking_api/knowledge/README.md)。

旧段落重排 Smoke 已删除。当前只读真实模型评估使用 `PYTHONPATH=apps/api/src apps/api/.venv/bin/python scripts/evaluate_wealth_v0113.py --answers-only --database /private/tmp/wealth_skills_test.sqlite --output /private/tmp/wealth_skills_test.json`，加载应用相同的标准技能与正文核验入口。脚本名称保留语义数据集版本，实际运行当前契约；只接受名称包含 test 的隔离库。

浏览器使用 wealth_browser_test_server.py，独立 test SQLite、API 8011、Web 3011；--advisor-history 仅用于独立库的合成旧对话。控制文件只注入测试业务时钟，不提供产品端推进时间接口，不改变授权 TTL。不得在原演示用户测评、下单或 reset。实际执行结果保存在对应版本更新说明。

选购入口回归位于 `test_wealth_advisory.py` 与 `wealth-analysis-interaction.test.mjs`：口头测评完成不能替代数据库记录；缺测评→实际测评→同对话完成消息须获得候选而无金融操作；指定简称须唯一介绍；点击购买先编辑，显式填写提交后才创建一次核对。旧版阻断意图读取需要本人+本对话双重范围，不能继承交易授权。隔离浏览器设施仍使用8011/3011和名称包含test的SQLite文件；资金最终提交只能在隔离环境验收。

理财选购呈现补充回归覆盖：预算元/万/亿与符号、多个金额澄清、收益诉求不误路由为
比较、历史预算主动重分析去重、已受理对话软删除后原订单继续结算及保留审计入口。
2026-10-11本轮完整后端934项（SQLite及banking_wealth_v011_test）通过；最后正文限制
补查顾问66项通过，前端98项交互通过。新推荐Skill不调用交易工具，检查事实/证据引用。

目录意图回归（2026-10-11）：完整后端942项，隔离SQLite/test PostgreSQL；顾问73项；
前端99项交互。实际浏览器在8011/3011先旧对话填5000元/进取/3个月，再新对话只问产品目录，
验证八款客观结果、未携带旧条件、内部栏目隐藏及条款点击；Organizer为隔离测试模型。

## v0.11.3 语义与正文验证

test_wealth_v0113覆盖数量、原文核验、需求更新、阶段、模型正文和Skill安全。自然表达集在apps/api/tests/data/wealth_v0113_expressions.json，开发40条、保留改写10条。scripts/evaluate_wealth_v0113.py仅允许名称含test的SQLite库，参数--database与--output指定隔离库和原始记录；--answers-only --independent评估独立场景。MODEL_GENERATED不等于语言质量满分，仍需人工核查。

浏览器设施支持--real-model，独立8011/3011端口和本地test时钟文件，正式产品无推进时间接口。开发和生产构建不能同时写同一个.next目录。具体检查结果见v0.11.3发布说明，不复用旧数量。

## v0.11.4 策略回归

`test_wealth_strategy.py`覆盖增长目标改变候选、集合反馈、换一批、逐款定位、偏好更新、策略关系、版本时间、历史资料不覆盖和持久Task不产生Operation。真实模型可执行 `scripts/evaluate_wealth_v0113.py --strategy --answers-only --database /private/tmp/wealth_strategy_test.sqlite --output /private/tmp/wealth_strategy_test.json`。脚本只接受test数据库，使用本次发布时间后的测试时钟，并记录每次核验失败及模型原答。真实生成与FakeLLM回归分开统计，人工复核上一批概括、代码泄漏和收益暗示。

## Tool 契约专项

`uv run --project apps/api pytest apps/api/tests/test_tool_contract_audit.py apps/api/tests/test_release_version.py` 检查 26 个登记契约、风险分类、权限和金额错误、推理续接、持久授权及动态订阅入账。仍须运行全量套件与隔离 PostgreSQL 测试；专项不能替代并发、租约与恢复验证。清单和边界见 [工具审计](../architecture/tools.md)。
