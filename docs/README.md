# 文档导航

当前说明对应 **v0.11.0 / Alembic 0034**，整理日期为 2026-10-09。先从 [项目 README](../README.md) 了解产品，再按需要阅读下列文档。

## 使用 Agent

| 文档 | 内容 |
| --- | --- |
| [账户、账单与报告](guides/financial-analysis.md) | 查询示例、分析期间、异常提示、报告与数据范围 |
| [转账、预约与 AA](guides/transfers.md) | 核对和授权、周期规则、参与者付款、状态与取消 |
| [模拟理财](guides/wealth.md) | 产品、风险测评、推荐、申购赎回、异步结算、资料及测试入口 |
| [订阅与消息](guides/subscriptions.md) | 识别、确认取消、恢复、续费提醒及模拟扣费 |

## 理解和开发系统

| 文档 | 内容 |
| --- | --- |
| [设计原则](architecture/design-principles.md) | 长期架构基线；最初制定于 v0.1，未来组件不视为已实现 |
| [系统架构](architecture/system.md) | Agent、Skill、Workflow、Tool、计划、Worker 与持久化职责 |
| [金融计算与计划约束](architecture/algorithms.md) | Decimal、期间、异常规则、条件 grounding、幂等恢复 |
| [安全与事实边界](architecture/security.md) | 身份、权限、风险、强验证、安全熔断、审计与已知限制 |
| [环境配置与升级](development/setup.md) | Docker、本地开发、关键配置、OIDC 和迁移 |
| [测试与演示](development/testing.md) | 自动化检查、隔离数据库、数据校验、Smoke、preflight 与 reset |

## 更新与历史

- [v0.11.0 更新说明](releases/release-notes-v0.11.0.md)
- [v0.10.3 更新说明](releases/release-notes-v0.10.3.md)
- [v0.10.2 更新说明](releases/release-notes-v0.10.2.md)
- [历史档案索引](archive/README.md)：各版本实现与测试、旧审查、架构图和验证来源。

旧 `report/` 已并入档案区。历史文档保留其记录日期和测试结论，带有明确历史标识；旧风险阈值、旧页面截图和当时待办不代表当前行为。当前指南发生变化时更新对应主题，版本执行证据留在更新说明或历史档案中。

- [v0.11.1 理财修复与体验优化](releases/release-notes-v0.11.1.md)

- [v0.11.2 理财分析、知识与连续追问](releases/release-notes-v0.11.2.md)
- [理财知识维护与检索评估](../apps/api/src/banking_api/knowledge/README.md)
