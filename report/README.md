# AI Banking Agent 项目审查与学习报告

基准：**v0.9.2 / Git `667dd9e`**。审查日期：**2026-10-05（Asia/Shanghai）**。

2026-10-09 更新的 [智能转账功能与实现说明](08-intelligent-transfer-guide.md) 基于当前 v0.10.2 工作区，包含最新收款人管理和界面修改；其时间基准与下述历史审查报告独立。

当前产品具备转账、账单分析、订阅管理三个场景方向的可演示链路，安全状态与金融计算主要由确定性后端控制。它仍是使用合成数据、Mock 银行 Provider 和 Mock 强验证的比赛原型，不能将 README 的 COMPLETE 等同于赛题全部示例或真实银行落地均已完成。

本轮发现并复现 **3 类新的边界问题**，另验证了 **1 项已知多进程实时通知限制**。既有回归通过不代表这些问题不存在。详见第一份报告。

| 阅读顺序 | 文档 | 内容 |
|---|---|---|
| 1 | [需求覆盖与 Bug 评估](01-requirements-and-bugs.md) | 逐项对照赛题、已实现/部分实现/未实现、问题复现和优先级 |
| 2 | [逐步实现说明](02-implementation-history.md) | 从 v0.1 到 v0.9.2，每一步的功能、实现方式和源码入口 |
| 3 | [网页测试教程](03-web-testing-guide.md) | 启动、准备数据、实际输入/点击步骤、预期结果、失败判定 |
| 4 | [当前系统架构](04-system-architecture.md) | 总体架构、转账时序、DAG、安全边界、持久化职责 |
| 5 | [核心算法](05-core-algorithms.md) | Agent Loop、Decimal 统计、风控、授权、订阅、异常、条件、恢复 |
| 6 | [验证与来源](06-verification-and-sources.md) | 本轮实际测试、历史证据区别、阅读清单和复现命令 |
| 7 | [后续实现顺序](07-future-implementation-plan.md) | 2026-10-07补充：未满足赛题功能的优先级、依赖、实现方法和验收里程碑 |
| 8 | [智能转账功能与实现说明](08-intelligent-transfer-guide.md) | 使用流程、架构图、状态与时序、授权、风险、幂等恢复、收款人管理、API 与源码入口 |

架构图另提供 [SVG 图片](assets/system-architecture.svg) 和 [PNG 图片](assets/system-architecture.png)，无需 Mermaid 插件即可查看。当前网页截图见 [Dashboard](assets/dashboard-v0.9.2.png)。

本轮实际结果：后端 **561 passed / 36 skipped**；新建隔离 PostgreSQL 库 **37 passed**；前端行为测试 **26 passed**；问题复现 **5 passed**（表示成功复现缺陷/限制，并非修复通过）。其他检查及执行范围见验证文档。

本轮仅新增 `report/` 内容，保留原有文档删除状态；没有修复业务代码、重置 Demo、执行新的网页资金提交或取消订阅。网页教程中的写业务由你操作，金额与风险预期都注明了初始状态条件。

- [转账扩展验证记录](09-transfer-extensions-validation.md)：备注、单次及按月周期预约、AA 和预约/对话管理 的测试与网页验收范围。
