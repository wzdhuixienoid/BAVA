# 本轮验证与阅读来源

审查日期：2026-10-05（Asia/Shanghai）；源码Git `667dd9e`，package/API v0.9.2。开始时工作区已有三项删除：`docs/learning-guide-v0.8.2.md`、`docs/system-architecture-v0.8.2.md`、`docs/web-workbench-ui-improvements.md`。本轮保留这些删除，只新增report及忽略的构建/测试缓存。

## 1. 本轮实际执行结果

| 检查 | 实际命令/方式 | 结果 |
|---|---|---|
| 后端静态检查 | apps/api下 `.venv/bin/ruff check . ../../scripts` | PASS |
| 后端默认全量 | `.venv/bin/pytest -q` | **561 passed / 36 skipped，18.02s** |
| PostgreSQL迁移 | 新建banking_report_20261005_test，再显式DATABASE_URL执行 `.venv/bin/alembic upgrade head` | 0001→0017 PASS |
| PostgreSQL集成 | 指向新隔离库的 `TEST_DATABASE_URL=... .venv/bin/pytest -m postgres -q --tb=short` | **37 passed / 560 deselected，7.30s** |
| 前端行为测试 | apps/web下 `node --experimental-strip-types --test tests/*.test.mjs` | **26 passed，0 failed**；Node module类型提示，无业务失败 |
| TypeScript | `node node_modules/typescript/bin/tsc --noEmit --incremental false` | PASS |
| ESLint | 临时NODE_PATH指向仓库 `.pnpm/node_modules`，运行 `node node_modules/eslint/bin/eslint.js .` | PASS |
| Next生产构建 | 相同临时NODE_PATH运行 `node node_modules/next/dist/bin/next build` | PASS，编译、lint/type、静态页与build traces完整 |
| Docker/HTTP | docker compose ps、GET /health、GET /api/v1/demo/readiness | API/Web Up、PG healthy，health ok，version0.9.2/head0017、初始余额/零exposure/正常Guard/Mock配置 |
| 网页只读验收 | 当前/dashboard，通过浏览器读取结构化页面，保存截图 | 4账户、August Golden、258订阅成本、3异常卡实际可见 |
| 边界复现 | report/verification/test_review_repros.py，FakeLLM+隔离SQLite+真实ASGI/校验器/引擎 | **5 passed，最后重跑0.77s**，含R01、R02、R03两货币变体、K01；PASS表示成功复现缺陷/限制 |

新的PostgreSQL库与运行Demo库分开，不运行测试库API worker，不改原Demo余额/订阅/写锁。测试会清理自己的隔离数据，所以不能将TEST_DATABASE_URL指向产品库。本轮完成后专用测试库保留，未删除其他库。

默认36 skipped不等于未验证关键数据库行为：独立PostgreSQL suite 37项实际通过，两套选择条件不宜直接加总为唯一用例总数。

本轮没有重新执行外部LLM smoke、10次报告稳定性、S1–S12全部浏览器写验收、真实OIDC/真实银行/MFA验收。没有调用新的网页资金提交/订阅取消，也没有实际复现资金损失。

## 2. 环境问题与解决方式

- `uv run`最初因默认缓存目录超出sandbox写权限失败；使用已安装 `.venv/bin`直接运行，无需安装依赖。
- pnpm最初触发运行前依赖检查和registry访问；改用已安装Node入口。当前依赖树的ESLint插件解析需临时NODE_PATH，未改项目依赖/安全配置。原生Next构建虽然退出0，但有ESLint插件错误；设NODE_PATH后完整重跑无该错误，采用最后完整成功结果。
- 新建PostgreSQL库首次直接运行tests出现36个表不存在setup error；先执行0017迁移后整套37项一次连续通过。属于环境准备遗漏，不作为Agent业务Bug。
- report位于apps/api pytest配置范围之外，因此复现必须显式 `-c pyproject.toml`，使用原隔离fixture。初次缺少该配置的async失败已纠正，不计入最终业务结论。

## 3. 重现检查命令

已有依赖时可直接运行（避免uv缓存/pnpm自动检查）：

```bash
cd apps/api
.venv/bin/ruff check . ../../scripts
.venv/bin/pytest -q
APP_ENVIRONMENT=test AUTH_MODE=development PYTHONPATH=tests \
  .venv/bin/pytest -c pyproject.toml \
  ../../report/verification/test_review_repros.py -q -s --tb=short
```

复现脚本**断言当前错误行为**，没有修复源码：修复后相应用例应改成正确语义的回归测试，而不是为了维持5 passed重新放回Bug。R02/R03通过Fake模型输出模拟错误提案/提取，证明服务器边界，不声称当前真实模型必现。

```bash
cd apps/web
node --experimental-strip-types --test tests/*.test.mjs
node node_modules/typescript/bin/tsc --noEmit --incremental false
NODE_PATH="$PWD/../../node_modules/.pnpm/node_modules" \
  node node_modules/eslint/bin/eslint.js .
NODE_PATH="$PWD/../../node_modules/.pnpm/node_modules" \
  node node_modules/next/dist/bin/next build
```

安装状态正常时，也可按README使用pnpm/uv。历史环境说明使用 `pnpm_config_verify_deps_before_run=false` 避免pnpm重复检查，不改变测试逻辑。

PostgreSQL首次准备需**先建隔离test库再迁移**：

```bash
# 仓库根；库不存在时执行一次
docker compose exec -T postgres createdb -U banking banking_report_20261005_test
cd apps/api
APP_ENVIRONMENT=test AUTH_MODE=development \
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_report_20261005_test \
  .venv/bin/alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_report_20261005_test \
  .venv/bin/pytest -m postgres -q --tb=short
```

## 4. 历史证据怎样使用

最新[版本测试记录](../docs/test-results-v0.9.2.md)和“v0.9-产品体验优化”最终对话说明：旧轮已完成真实report/plan/audit/security smoke、固定报告10次全等、S1–S12，以及最后reset/preflight。较早同一对话曾标NOT READY，后续验收已收口为READY，不应只截取旧结论。

这里把它们写为**历史记录**，没有冒称本轮重新执行。v0.9.2原scope READY也不表示本轮新发现的R01–R03已修复，更不表示全部赛题或生产银行落地READY。架构基线中的未来组件不能当作当前已实现。

## 5. 阅读来源清单

从[README](../README.md)开始；遍历docs现存74份Markdown（约11079行），重点核对22份implementation report、各版本test-results、Golden、Runtime comparison、architecture baseline与当前repo tree。目录与标题清单见 [docs-inventory.json](verification/docs-inventory.json)。不存在的三份文档只作为工作区删除/历史对话信息记录，没有恢复为现存文档。

项目Codex对话经read_thread读取12个关联对话、56轮，均无剩余分页；重点核对交付结论、修复及验收补做过程。精简来源信息见 [conversation-inventory.json](verification/conversation-inventory.json)，没有复制工具日志、隐藏推理或凭证。

| 对话原始标题 | 关联功能 |
|---|---|
| v0.1-搭建骨架 | Bootstrap、Docker、PostgreSQL/SSE持久化 |
| v0.2-实现最小 Agent Loop | 最小查询Agent、LangGraph、checkpoint |
| v0.3-Financial Analysis | 统计、Router、Skill、Report产品 |
| v0.4-转账工作流 | 草稿、授权、Reauth、Operation |
| v0.5-Production Reliability | Recovery、并发余额、Outbox、Task执行 |
| v0.6.1-身份认证 | OIDC/JWT、Principal、ownership |
| v0.7.1-动态风险分级 | exposure、风险升级、用户锁 |
| v0.7.2-订阅与代扣管理 | 周期检测、订阅取消 |
| v0.7.3-异常交易识别与安全熔断 | anomaly、Guard、TOCTOU修复 |
| v0.8-任务规划与跨场景编排 | DAG、条件、原文threshold grounding |
| v0.8.3-agent教程与页面优化 | 旧学习文档、统一回复与完成索引 |
| v0.9-产品体验优化 | typed facts、Dashboard、Audit、最终实际验收 |

主要源码和测试核对范围：`main.py`、Domain/Registry/Policy、LLM/Context/LangGraph、Task与worker、Workflow/Operation/Provider/Risk/Guard、Financial/Skill/Report、Subscription/Anomaly、Plan/Condition/Threshold、Audit、认证/owner routes、Web卡片/页面/SSE、相关tests和scripts。具体模块入口分布在各报告，未把“读了目录”当“每一行均完成形式化安全证明”。

## 6. 交付边界

新文档、架构图、截图、来源清单、问题复现脚本均在report。业务源码、历史文档和数据库迁移未修改；已有删除保持原样。检查没有新建PR、commit/tag、push或生产发布。R01–R03为本报告建议后续修复项，本轮仅诊断和记录。
