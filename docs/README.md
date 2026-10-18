# 文档导航

当前版本为 **v1.0.1**，数据库迁移 head 为 **0038**。本文档集只说明当前代码与交互；应用版本以包配置为准，Skill 资源、接口契约和业务资料各自独立版本化。

## 使用指南

| 文档 | 内容 |
| --- | --- |
| [项目入口](../README.md) | 能力、启动、页面、示例与限制 |
| [账户、账单与消费报告](guides/financial-analysis.md) | 查询期间、分页、总览、报告与异常通知 |
| [转账与收款](guides/transfers.md) | 转账分析、收款人、即时／预约／周期转账与 AA |
| [订阅与消息](guides/subscriptions.md) | 识别、取消、恢复、模拟扣费及站内提醒 |
| [模拟理财](guides/wealth.md) | 目录、测评、推荐、追问、申赎和异步状态 |
| [多步骤任务与条件](guides/plans.md) | 计划能力、条件证据、用户等待、手动接管与安全回退 |
| [免密额度与身份验证](guides/security.md) | 金融总览中的额度设置、私密验证码和后端审计 |

## 系统架构与六层职责

先读 [系统架构](architecture/system.md)，再按同一职责框架阅读六层说明。

| 层 | 独立说明 | 当前实现 |
| --- | --- | --- |
| Agent | [Agents 总览](architecture/agents/README.md) | PersonalBanking、SubscriptionAnalysis、WealthAdvisor 三个只读业务执行者 |
| Agent Skill | [Skills](architecture/skills.md) | 八个标准包、三个 Python 业务绑定、按需加载与资源校验 |
| Tool | [Tools](architecture/tools.md) | 19 个读取、5 个提交、3 个对账能力及 caller／风险约束 |
| Workflow | [Workflows](architecture/workflows.md) | 转账、订阅取消／恢复、理财申购／赎回的确定性办理 |
| Plan | [Plans](architecture/plans.md) | 静态高层能力、持久 DAG、条件、等待与受限回退 |
| Domain API | [Domain APIs](architecture/domain-api.md) | 页面资源、明确用户动作、身份归属及前端契约 |

### 三个 Agent 的同规格详情

| Agent | 说明 | 覆盖内容 |
| --- | --- | --- |
| PersonalBankingAgent | [个人银行](architecture/agents/personal-banking.md) | ACCOUNT／SPENDING／COMBINED、账单、消费、报告与续页 |
| SubscriptionAnalysisAgent | [订阅分析](architecture/agents/subscription-analysis.md) | 唯一分析工具、费用／续费事实、管理边界与工作流交接 |
| WealthAdvisorAgent | [理财顾问](architecture/agents/wealth-advisor.md) | 七项读取、按场景技能、事实／证据、追问、降级及交易交接 |

三个详情均按职责与入口、Skill 与工具、执行与结果、边界与失败处理、源码与验证组织。

### 跨层规则

| 文档 | 内容 |
| --- | --- |
| [金融计算与规则](architecture/algorithms.md) | Decimal、消费口径、异常规则、幂等与条件计算 |
| [安全与事实边界](architecture/security.md) | 身份、授权、风险、证据与结果可信度 |
| [独立分析代码沙箱](architecture/sandbox.md) | 无网络、无银行权限、资源限制与执行审计 |

## 参赛资料

| 文档 | 内容 |
| --- | --- |
| [作品简介与提交资料](competition/submission.md) | 作品名称、少于200字简介和文件对应 |
| [安全自评报告](competition/security-assessment.md) | 权限矩阵、安全证据与已知风险 |
| [演示与验收](competition/acceptance.md) | 四场景、安全演示和可重复检查 |
| [第三方组件与来源](competition/third-party.md) | 依赖、资料及作者提交前核对事项 |

## 开发与维护

| 文档 | 内容 |
| --- | --- |
| [环境配置与升级](development/setup.md) | Docker、本地开发、开关、OIDC 和数据库迁移 |
| [测试与演示](development/testing.md) | 自动检查、隔离数据库、合成数据及真实模型评估 |
| [运行与文档维护](development/operations.md) | 启停、备份、状态排查、恢复和文档维护规则 |

## 模块说明与运行资源

源码目录 README 只解释模块职责及维护入口，细节以对应架构／指南为准。

- [Agents](../apps/api/src/banking_api/agents/README.md)、[Tools](../apps/api/src/banking_api/tools/README.md)、[Workflows](../apps/api/src/banking_api/workflows/README.md)
- [Agent Skills 包](../apps/api/src/banking_api/agent_skills/README.md)、[Python 业务绑定](../apps/api/src/banking_api/skills/README.md)
- [知识维护](../apps/api/src/banking_api/knowledge/README.md)、[审计](../apps/api/src/banking_api/audit/README.md)、[上下文范围](../apps/api/src/banking_api/memory/README.md)
- [PostgreSQL](../infra/postgres/README.md)

`agent_skills/**/SKILL.md` 和 references 是实际加载的指令，知识 JSON、产品资料及测试基准也是运行／验证资源。其版本和来源日期不是应用发布记录；更新需遵守对应绑定、hash 和历史证据约束。
