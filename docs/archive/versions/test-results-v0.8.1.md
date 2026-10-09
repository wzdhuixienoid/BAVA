# 历史档案：v0.8.1 测试结果

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

日期：2026-09-30（Asia/Shanghai）。使用现有本地依赖；UV_NO_SYNC=1、UV_CACHE_DIR=/private/tmp/banking-uv-cache 仅用于避免受限目录写入和无必要的依赖重新安装。

## 最终 Backend regression（一次）

```bash
cd apps/api
uv run ruff check . ../../scripts
uv run pytest -q
```

- Ruff：All checks passed。
- Pytest：**303 passed, 29 skipped，10.92s**。
- 29 个 skip 为需要 TEST_DATABASE_URL 的 PostgreSQL cases，随后在真实 PostgreSQL 验证。
- 完整 regression 后收尾修正了两个 Router 边界：订阅分析不会因通用“分析”一词被拆成 DAG；中英文 conditional 请求拒绝。依用户要求未重跑完整历史 suite，复测相关 Plan / Router / routing integration：**85 passed，3.05s**；对应 Ruff 通过。

## PostgreSQL suite（一次全量调度，失败/未完成部分定向补测）

```bash
TEST_DATABASE_URL=postgresql+asyncpg://banking:banking@localhost:5432/banking_test \
  uv run pytest -q -m postgres
```

全部 **30 个 marked cases 已覆盖通过**，包括：

- 0015→0016 downgrade/upgrade 验证，Plan 三表与索引/约束。
- source_task_id UNIQUE、两步依赖图持久化。
- 真正 PostgreSQL Task attempt fencing：旧读取结果不能完成 Step/Plan 或生成最终 Message。
- UNKNOWN Operation 后 WRITE_LOCKED，Recovery 查询同一事实并唤醒同一个父 Task。
- 历史 Operation / Task / Outbox / 风险并发 / Provider concurrency 回归。

执行细节如实记录：

1. 开发阶段仅 Plan PostgreSQL 定向验证：4 passed，1.00s。
2. 最终一次全量 suite：19 passed，1 failed，挂在旧竞态测试观察点后主动中断。失败来自 fixture 未清理持久化 synthetic 订阅 cancellation ledger；挂起来自新的 user lock 先于旧测试的 require_write_allowed 观察点。
3. fixture 纳入 mock_subscription_cancellations 清理；竞态观察改为准备请求入口；旧“同一 Operation 也应被锁阻止”断言更新为“原 Operation 返回同一 ID，新 Workflow 的 Operation 仍被阻止”。未修改 Recovery 主算法、Provider lock 或资金算法。
4. 仅失败场景 + 三个受影响/未完成竞态 cases：**4 passed，1.19s**。
5. suite 尚未执行的 Provider concurrency 文件：**7 passed，0.49s**。
6. 19 + 4 + 7 = 30 个不同 PostgreSQL cases 最终均通过，没有第二次重跑完整 PostgreSQL suite。

唯一 warnings 是现有 Alembic 配置缺 path_separator 的 deprecation 提示；不影响迁移结果，未扩展本版 schema/config 范围。

## 新增测试

- test_plans.py：**54 cases**（收尾前 52 cases，后增加单能力订阅/英文条件路由边界）。
- test_plan_postgres.py：**4 cases**。
- 覆盖 schema/内部字段拒绝、unknown Tool/Capability、cycle、重复/缺失依赖、步数限制、多写拒绝、graph retry、Workflow 链接 crash window、人工接管中断、resume、只读 rollback、跨副作用 rollback 拒绝、Principal ownership、Prompt Injection 和最终回答事实边界。
- 覆盖 Planner Transfer 的 no Approval / RED no Reauthentication / WRITE_LOCKED → 0 Operation。
- Transfer / Subscription 已有 Operation + response-loss 模拟 + 后续 WRITE_LOCKED：同一 operation_id/key、单一 Operation、Provider fact 至多一次。

## 真实 HTTP + 当前 LLM 产品 Smoke

最新代码 API 在 127.0.0.1:8001 启动，使用单独新建的 banking_plan_smoke_test synthetic 数据库、当前 .env 的 LLM 配置和真实 TCP HTTP。未修改现有 banking 演示库；不输出密钥或 hidden reasoning。

```bash
uv run --project apps/api python scripts/smoke_plan_product.py
```

- **Smoke A PASS**：原请求“先查一下工资卡余额，再分析一下2026年9月的消费。” → COMPLEX_PLAN → ACCOUNT_QUERY + FINANCIAL_ANALYSIS → 两个 bounded result → Plan/Task COMPLETED。
- **Smoke B PASS**：原请求“先看看我有哪些订阅，然后取消星幕视频。” → SUBSCRIPTION_ANALYSIS COMPLETED → cancellation WAITING_USER；YELLOW、Operation=0、无 Reauthentication。明确 approve + commit 后同一 Operation SUCCEEDED → Workflow/Step/Plan/Task COMPLETED。再次 commit 返回相同 operation_id。
- 临时 API 已停止；隔离数据库保留该次产品结果。脚本需要新的 isolated synthetic database，重复使用已取消的同一订阅会如实显示当前业务状态。

## Frontend（各一次）

OpenAPI 从最新本地 app 导出到临时 JSON，OPENAPI_URL 指向该文件，避免从尚未更新的 8000 容器生成旧 schema。

```bash
pnpm api:generate
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

四项均 **PASS**。Next.js production build 编译成功，7 个静态页面生成成功。PlanCard 使用生成类型，复用已有 Workflow Cards，没有第二套 Approval / Reauth / Commit UI。

未重跑历史 Docker crash smoke、异常检测 smoke、订阅 detector smoke 或 external IdP smoke。没有安装依赖、接真实 IdP、部署或修改现有 Docker 产品服务。
