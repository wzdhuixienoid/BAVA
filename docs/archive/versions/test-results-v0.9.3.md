# 历史档案：AI Banking Agent v0.9.3 Test Results

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

日期：**2026-10-07，Asia/Shanghai**。版本：**0.9.3**。Alembic head：**0019**。

记录本次管理功能、浏览器反馈和版本同步的实际检查。自动化测试、Mock 浏览器验收、现有本地实例读取和真实模型测试分别列出；未执行项目不标为通过。

配套：[实现报告](implementation-report-v0.9.3.md)、[目录树](repository-tree-v0.9.3.md)、[浏览器过程与截图](banking-management-repairs.md)。

## 1. 环境与阶段

本机 macOS，Python 3.12、Node.js、Next.js 15.5.2、Docker Compose、PostgreSQL 17。后端使用现有 `apps/api/.venv`；前端直接调用已安装 Node 工具，避免本机 pnpm 自动依赖检查触发额外安装。

- **管理功能阶段**：SQLite 后端测试；独立 `banking_management_01a11570_test` PostgreSQL 数据库验证迁移与并发；临时 8001／13001 API/Web 使用 Fixture LLM 和真实 Workflow／Worker／Mock Provider。
- **浏览器反馈阶段**：新增快捷选择及回答去重后，实际在 3000 工作台检查已有历史数据、同名选项和新增页面返回流程，没有选择或提交用户当前转账。
- **0.9.3 版本同步阶段**：再次运行全部非 PostgreSQL 后端测试、前端测试、版本一致性检查及 Docker 构建。PostgreSQL 39 项结果来自本轮前面的管理功能阶段，未将其描述为版本号同步后的重跑。

独立 PostgreSQL 测试库及临时验收服务已清理。现有本地 Docker 数据没有 reset；已有对话、业务与审计保留。

## 2. 自动化检查

| 检查 | 实际命令／阶段 | 结果 |
| --- | --- | --- |
| 后端完整非 PostgreSQL 回归 | 仓库根：`apps/api/.venv/bin/python -m pytest apps/api/tests -q -m 'not postgres' --tb=short`；版本同步后 | **584 passed，39 deselected，20.27s** |
| PostgreSQL 回归 | 同一 pytest 入口，`-m postgres`，设置独立 `TEST_DATABASE_URL`；管理功能阶段 | **39 passed，576 deselected，8.29s** |
| 前端展示和行为 | `apps/web`：`node --experimental-strip-types --test tests/*.test.mjs`；版本同步后 | **31 passed，0 failed** |
| 后端及改动脚本 Ruff | 源码、测试、迁移、reset／preflight／Audit smoke 脚本 | **PASS** |
| 改动脚本语法 | `python -m py_compile scripts/demo_preflight.py scripts/smoke_audit_product.py` | **PASS** |
| 版本一致性 | JSON／TOML／API source／实际 FastAPI OpenAPI 校验 | **PASS，均为 0.9.3** |
| 前端 ESLint、TypeScript、生产编译 | 本机检查及 `docker compose build api web` 中 Next.js 构建 | **PASS** |
| Markdown 链接、目录树与 diff 空白 | 本版文档静态检查、`git diff --check` | **PASS** |

前端 Node 测试有既有 `MODULE_TYPELESS_PACKAGE_JSON` 提示，不影响 31 项通过。未修改项目 module mode 来隐藏该提示。

本次执行日志保存在本机 `/private/tmp/banking-v093-backend.log`、`banking-v093-web.log`、`banking-v093-docker-build.log`；前一阶段 PostgreSQL 结果为 `/private/tmp/banking-postgres-final.log`。这些是临时本机日志，不是部署依赖或不可变审计归档。

## 3. 关键后端覆盖

| 要求 | 主要测试入口 | 结果 |
| --- | --- | --- |
| 0.01／1／小额／大额转账均 RED | `test_management_repairs.py`、`test_transfer_risk.py` | PASS |
| 未确认、验证失败／过期或旧验证不能创建 Operation | `test_transfer_authorization.py`、`test_transfer_operations.py`、`test_security_adversarial.py` | PASS |
| 旧黄色待提交草稿按新规则显示，历史状态保留 | `test_management_repairs.py`、前端 product visualization | PASS |
| 删除活动拦截、重复删除、越权 404、保留记录 | `test_management_repairs.py` | PASS |
| 删除与消息发送行锁竞争 | `test_management_postgres.py`，八轮并发场景 | PASS |
| 收款人确认、重复保存、持久化、用户隔离及完整转账 | `test_management_repairs.py` | PASS |
| 缺少姓名／无匹配时快捷选择，按姓名＋ID 校验且拒绝外部 ID | `test_transfer_payee_shortcuts.py` | PASS |
| 新增后选择、旧匹配失败恢复、删除后不能恢复 | `test_transfer_payee_shortcuts.py` | PASS |
| 快捷更换收款人使确认和验证失效、旧版本拒绝 | `test_transfer_payee_shortcuts.py` | PASS |
| “我可以给哪些人转账”只读路由，不依赖模型分类 | `test_request_router.py` | PASS |
| 取消→恢复→再取消，重复提交及零即时扣款 | `test_management_repairs.py` | PASS |
| 恢复强验证失败／过期、价格变更导致旧授权失效 | `test_management_repairs.py` | PASS |
| 恢复响应超时后查询原动作，不重复生效 | `test_management_repairs.py` | PASS |
| 两个 Provider 连接在 PostgreSQL 串行更新合同版本 | `test_management_postgres.py` | PASS |
| 旧取消事实可恢复、日历短月／闰年／过期账期 | `test_management_repairs.py` | PASS |
| Demo 生产环境拒绝、版本／迁移检查、重置新增数据 | `test_demo_preflight.py`、`test_demo_reset.py` | PASS |

测试中只发生 synthetic Mock 银行业务。未执行真实银行转账、真实商户合同签署或真实强验证。

## 4. 关键前端覆盖

`apps/web/tests/` 中 31 项覆盖现有账户、审计、回复关联、业务成功判断及本轮新增场景：

- 历史订阅快照不渲染分析卡，正文不因快照折叠。
- 收款人查询只有文字回答，持久化 `payee_results` 不重复渲染。
- 收款人步骤含已有／新增入口，同名账户显示不同银行和尾号，链接保留原对话上下文。
- 恢复使用强验证和恢复回执，不显示成“已取消”。
- 旧 READY_FOR_COMMIT 草稿缺少验证证据时不宣称验证完成。
- UNKNOWN、失败或仅 Task COMPLETED 不生成成功回执和完成索引；关键账户金额继续使用后端结构化事实。

## 5. 实际浏览器记录

| 场景 | 环境 | 可见结果 |
| --- | --- | --- |
| 新增收款人→对话查询→一元转账 | 独立 SQLite／Fixture LLM／Mock Provider | 保存后可查询；RED→确认→模拟强验证→提交→成功 |
| 活动流程拦截删除、完成后删除、当前对话切换和空列表 | 同上 | 活动时拒绝；完成后移出列表；切换剩余对话，空列表显示新建引导 |
| 总览取消链接、空列表预填及取消 | 同上 | 用户发送后建立流程，确认后 Provider 成功取消 |
| 恢复预填、RED 强验证、执行及普通订阅查询 | 同上 | 恢复回执明确“本次未扣款”；普通回答无分析卡，只有一次总览提示 |
| 收款人文字回答和侧栏清理 | 现有 3000 实例 | 历史重复框消失，开发标签和 UUID 不显示 |
| 快捷已有列表、新增入口及返回 | 现有 3000 实例 | 两位张三按银行／尾号区分；新增页可返回原草稿，没有替用户选择或确认 |

截图：

- [恢复成功与强验证](../../assets/banking-management-resume.png)
- [删除后切换](../../assets/banking-management-delete.png)
- [收款人回答去重](../../assets/banking-management-payee-answer.png)
- [收款人快捷入口](../../assets/banking-management-payee-shortcuts.png)

截图是检查当时的界面；0.9.3 版本号在后续元数据同步时更新，不把旧截图当作新版本标签验证。

## 6. 迁移和本地运行

本轮实际执行 PostgreSQL 0017→0018，回填旧成功取消状态；并发／迁移回归通过。正常本地库升级前 `RUNNING` Task 和未收敛 Operation 均为零，暂停 API/Web、备份、迁移并启动新镜像，没有清空原有两条对话。

正常本地实例的 `/health`、对话、收款人和订阅 API 返回 200，3000 页面实际可打开，SSE 正常。迁移前备份为 `/private/tmp/banking-local-before-0018-20261007.dump`，只允许当前用户读取。

版本同步后实际读取 OpenAPI／readiness：API 版本为 0.9.3、数据库 head 为 0018、未收敛 Operation 为零；工作台和 Dashboard HTTP 200，页面标签均为 v0.9.3。当前用户已有转账测试记录，`salary_balance_initial` 和 `daily_exposure_zero` 为 false；这是正常数据事实，没有执行 reset 或宣称 Demo preflight 全部通过。preflight 要求初始余额、零日暴露、fixture 订阅和正常 Guard，不能为让检查通过而自动清空用户数据。

## 7. 未重新执行的项目

| 项目 | 本版状态 | 说明 |
| --- | --- | --- |
| 真实模型报告／Plan／Audit／Security smoke | NOT RUN | v0.9.2 历史结果保留；Audit 脚本本版已适配 RED＋Mock 强验证，只有静态检查与相关 API 回归证据 |
| 十次真实模型报告稳定性 | NOT RUN | 不重复引用 v0.9.2 的 10/10 为本版执行结果 |
| S1–S12 全套真实产品人工浏览器验收 | NOT RUN | 本版只重新检查本次变更涉及的 Mock 页面流程 |
| 本轮新增移动端专项验收 | NOT RUN | 既有响应式实现保留，本版没有重新宣称通过所有尺寸 |
| 外部 IdP、真实银行／商户、真实 MFA | NOT IMPLEMENTED / NOT RUN | 仍使用既有 OIDC-ready 边界及 Mock 服务 |

结论：本版修复范围的自动化和所列 Mock 页面流程通过；可在本地测试 0.9.3。没有执行 Git commit／tag／远端发布，也不把 Mock 验收当作真实金融接入认证。

## 账单分析故障修复后的定向回归

- 后端非 PostgreSQL 回归：**587 passed，39 deselected**，19.44 秒。
- 财务／报告路由定向回归：**44 passed**，包含自然年边界、上年比较、年度报告持久化、日期上下文、预算收尾与缺少报告数据。
- 前端测试：**31 passed**；TypeScript、ESLint 及 Docker API/Web 生产构建通过。
- 真实配置模型＋本地 Mock 数据：原句“最近账单有异常吗”成功，仅一次工具调用；“8月份账单报告”成功产生 `2026-08` 报告；“2026年度账单报告”成功产生 `2026` 报告。
- “2025年8月账单报告”没有对应数据时返回明确说明，无报告 Artifact，无内部快照错误。
- 扩容前生成的年度报告在浏览器确认总支出 ¥42,388.10、总收入 ¥95,200.00、消费笔数 128；报告引用结构化账单事实。

本轮没有数据库结构变化，未重跑 PostgreSQL 并发／迁移测试。上述真实模型定向验收不等同于完整稳定性批跑或 S1–S12 重跑。日志：`/private/tmp/banking-analysis-final-tests.log`、`banking-analysis-live.log`、`banking-analysis-recent.log`、`banking-analysis-release-build.log`。

## 模拟历史扩容后的回归

- 数据校验通过：4 个账户、6 个收款人、5 个合同、1,207 笔；连续 21 个完整月份及本月部分数据。
- 后端非 PostgreSQL 回归：**590 passed，39 deselected**，21.01 秒。旧七八月黄金金额与排名保持不变。
- 新增生成器可重现性、全月份／年度独立 Decimal 参考，以及四类异常场景覆盖测试。年度和月度统计继续排除待入账、撤销和内部转账。
- 生成器及 validator Ruff、fixture 验证、Docker API 构建通过；本次没有数据库迁移。

记录扩容前生成的不可变报告仍展示其旧数据；新报告使用扩容后的账单，不覆盖历史报告或清空用户业务。日志：`/private/tmp/banking-expanded-release-tests.log`、`banking-expanded-release-build.log`、`banking-expanded-live.log`。

扩容后本地真实模型四条定向请求全部 COMPLETED：

| 请求 | 工具次数 | 验证结果 |
| --- | --- | --- |
| 2025年度账单报告 | 4 | 生成并在浏览器打开，支出 ¥112,431.45、收入 ¥271,440.00、消费 653 笔 |
| 2025年2月消费分类统计 | 1 | 返回 2025-02 分类与金额 |
| 最近账单有异常吗 | 1 | 返回近期有界异常快照 |
| 本月消费分析统计 | 2 | 返回 2026-10 汇总及分类，说明月份尚未结束 |

近期默认完整月份的修复另经真实请求确认返回 2026-09；全部扩容后月份与年度金额由独立 Decimal 参考回归校验。无数据说明在扩容前已验证，原测试中的无账单期间现移至 2024-01。浏览器截图：本机 `/private/tmp/banking-expanded-yearly-report.png`。

## 对话名称与一次性预填回归

- 后端：597 passed，40 deselected（24.71 秒）。新增首次命名、后续保持、手动默认名称保护、校验、越权及删除后拒绝。
- 前端：34 passed，TypeScript、ESLint 和 Docker API/Web 构建通过。覆盖预填消费一次、再次显式点击和保留 URL 其他参数及 history state。
- 独立 PostgreSQL banking_titles_test 从初始迁移至 0019：40 passed，597 deselected（8.09 秒），包含手动改名与首次回复并发。测试库随后删除，没有清空用户数据库。
- 部署前备份本机数据库至 /private/tmp/banking-before-0019-20261007.dump，权限 600。

日志：/private/tmp/banking-titles-final-tests.log、banking-titles-postgres.log、banking-titles-web.log、banking-titles-build.log。

浏览器验收：独立测试标签页访问恢复链接，输入框首次显示「恢复活力健身订阅」，URL 自动清除 resume。点击新建对话后输入为空；发送只读账户查询后侧栏与标题自动变为「我有哪些账户」。改名为「名称保存验收」并刷新，侧栏和标题仍保持，输入框为空。没有发送恢复订阅请求或修改用户原标签页的草稿。截图保存在 /private/tmp/banking-title-auto.png 与 /private/tmp/banking-conversation-title-verified.png。运行实例数据库已确认 head 0019。
