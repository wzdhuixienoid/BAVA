# v0.8.2 Test Results

最终 correctness 验证日期：2026-10-02。以下采用最后完整成功的各套运行，均在最终 v0.8.2 功能代码和测试状态执行。开发定向测试和较早轮次不作为完整回归数量拼接。

## 最终完整 Backend regression

工作目录 `apps/api`：

```bash
UV_CACHE_DIR=/private/tmp/banking-uv-cache UV_NO_SYNC=1 uv run ruff check . ../../scripts
UV_CACHE_DIR=/private/tmp/banking-uv-cache UV_NO_SYNC=1 uv run pytest -q
```

```text
All checks passed!
481 passed, 34 skipped in 13.84s
```

未配置 TEST_DATABASE_URL 的完整后端运行中，需要数据库的用例按 fixture 跳过。下面另一次完整 PostgreSQL suite 已验证全部 PostgreSQL 标记用例。UV_CACHE_DIR 与 UV_NO_SYNC 仅用于当前本地缓存权限及已有环境，不改变测试选择。

## 最终完整 PostgreSQL suite

工作目录 `apps/api`：

```bash
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
UV_CACHE_DIR=/private/tmp/banking-uv-cache UV_NO_SYNC=1 \
uv run pytest -q -m postgres
```

```text
35 passed, 480 deselected in 7.05s
```

本次仅在 alembic.ini 增加 path_separator=os，完整 PostgreSQL suite 无 warning（path_separator deprecation 为 0）；没有失败或 skipped PostgreSQL 用例。这是最后一次完整 suite 的连续结果，不是多个定向片段之和。覆盖 0015→0016 历史迁移与恢复至 head、0016→0017 真实旧数据保留、Condition Spec/Decision/guard 持久化、source_task_id Plan 唯一性、Task fencing、条件 FALSE 零写入、条件 TRUE handoff/接管/resume、既有 Operation + WRITE_LOCKED、UNKNOWN Recovery 及历史 Provider 并发回归。

## 新增条件测试

`test_plan_conditions.py` 共 88 个展开后的用例，`test_plan_conditions_postgres.py` 新增 5 个 PostgreSQL 用例。覆盖：

- strict kind union、禁止 authority/实际值/结果/表达式/JSON path、threshold 只接受有限非负 Decimal 字符串；>= 的中文同义词。
- predicate/source mismatch、source/guard 依赖、未知 predicate、ELSE、嵌套、两个 Condition 上限和一个 write 上限；查询加条件及两个独立条件合法。
- Decimal 精度/等值边界、canonical hash、金额/账户/月份缺失、非法输入、币种不匹配、订阅多币种需要显式选择。
- TRUE guarded read、FALSE read/write、无效条件 FAILED、正常条件跳过的传递，以及另一依赖 PENDING 时的多依赖 join。
- FALSE 零 Workflow/Approval/Reauthentication/Operation/Provider 转账事实，且最终中文不声称转账成功。
- TRUE 仍 WAITING_USER，RED 无 reauth 和 WRITE_LOCKED 不能创建新 Operation；不可强制 TRUE 或跳过确认。
- Task retry 复用 Planner/Decision、旧 Condition Worker 不能覆盖新 attempt、Workflow 创建后 link 前 crash 的幂等恢复。
- rollback 清除 Decision 并改变 source hash，含写 Capability 的 rollback 即使 FALSE 也拒绝。
- 原始 Message 边界、服务器 Principal scope、manual take-over 后业务手动完成、resume 复用 Decision。

## Threshold grounding 收尾验证

新增 `test_condition_threshold_grounding.py` 共 88 项：原始 Message 条件从句的 predicate/金额匹配，Arabic/Decimal/逗号分组/货币符号/中文整数，业务金额与阈值区分，Decimal 等价，模糊条件与注入、错误 threshold、不能自报 threshold_source、币种冲突和缺币种声明、后端绑定用户明确币种、非法或歧义数字 fail closed。集成测试使用真实 Router/Task/Plan 调用链及 FakeLLMProvider：缺阈值或试图丢弃模糊条件时 0 Plan / Workflow / Operation；Fake Planner 绕过提案校验也会在持久化前被拒绝；明确本月消费阈值继续原只读执行。Task 错误给出明确金额示例。

开发仅定向执行 grounding、条件/Router 回归及配置/迁移测试；grounding 最终专项 88 passed，Alembic 升降级与条件原始请求定向 3 passed，均无 path_separator warning。上面两套最终完整运行各自一次通过，不拼接定向结果。没有修改 ConditionEvaluator、业务 payload、持久化 schema 或 migration；版本保持 v0.8.2。

## Frontend checks（初始 v0.8.2 记录）

本次 correctness 修复未改 API response schema 或前端，未重复 OpenAPI 生成或 frontend checks；以下保留初始交付结果。

从当前源码导出 `/private/tmp/banking-v082-openapi.json`，避免旧 Docker API 的 schema：

```bash
OPENAPI_URL=/private/tmp/banking-v082-openapi.json pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

全部 PASS。生产构建成功，生成 7/7 静态页面；没有新 Conditions 页面。PlanCard 只展示后端 Spec/Decision、实际值、阈值、币种、结果和 guard，不在浏览器比较金额。

## 真实 HTTP / 当前 LLM 产品 Smoke（2026-09-30 记录）

本次以模糊条件原始 Message 的集成测试证明不会启动无条件 Workflow，没有重跑历史 A/B 或其他产品 smoke；以下保留初始交付记录。

当前工作区 API 在临时端口 8001 运行，独立 synthetic PostgreSQL 数据库 `banking_condition_smoke_test`，从空数据库迁移至 0017。使用当前配置 LLM 和真实 TCP HTTP，不使用 FakeLLMProvider。执行脚本：

```bash
DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_condition_smoke_test \
UV_CACHE_DIR=/private/tmp/banking-uv-cache UV_NO_SYNC=1 \
uv run --project apps/api python scripts/smoke_plan_conditions.py
```

完整 A/B 同一轮 PASS：

| 场景 | 事实与结果 |
|---|---|
| A：工资卡余额不少于999999元则给张三转500 | ACCOUNT_QUERY COMPLETED；Condition FALSE；TRANSFER_WORKFLOW SKIPPED / CONDITION_NOT_MET；Plan / Task COMPLETED；中文明确未启动转账 |
| A 数据库独立断言 | workflows=0、approvals=0、reauthentications=0、operations=0、mock_bank_transfers=0 |
| B：工资卡余额不少于3000元则给张三转500 | Condition TRUE；明确经原 API 选择张三候选项；READY_FOR_REVIEW、YELLOW；Plan / Task WAITING_USER；Operation=0 |
| B 用户操作后 | 明确 approve + commit；Workflow / Operation SUCCEEDED；全部 Step、Plan、Task COMPLETED；Decision 保持原值 |
| B 数据库独立断言 | workflows=1、approvals=1、reauthentications=0、operations=1、mock_bank_transfers=1 |

B 开始前不存在写记录或历史转账 exposure，实际 Risk 为 YELLOW，未绕过 Risk、Approval 或 reauth。前一次 smoke 脚本发现读取 conversation/required_input response 结构不正确，修正后采用以上完整成功轮次。可选 C 未运行；订阅成本条件与取消、UNKNOWN 和写锁恢复由新增 PostgreSQL 用例覆盖。

临时 8001 API 已停止；保留隔离 synthetic 数据库证据。没有重新做外部 IdP、旧 Docker crash、异常交易产品或订阅检测器产品 smoke；原部署未修改。
