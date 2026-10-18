# 作品简介与提交材料

## 作品名称与简介

作品名称：AI Banking Agent · 智能银行助理。

以下简介正文少于200字，可用于报名系统：

> 以自然语言缩短银行业务路径，构建可理解、可核对、可追溯的智能银行助理。系统结合大模型意图识别、LangGraph工具编排、专业技能和持久化DAG，覆盖模拟转账、账单分析、理财与订阅管理。通过确定性金融计算、绿黄红权限分级、事实约束、操作审计和隔离分析沙箱控制执行，并提供可选TOTP验证能力。

## 提交文件对应

| 资料 | 本地入口 |
| --- | --- |
| 架构与架构图 | [system.md](../architecture/system.md)，包含可渲染 Mermaid 图 |
| 核心算法 | [algorithms.md](../architecture/algorithms.md) |
| 安全设计 | [security.md](../architecture/security.md)、[沙箱](../architecture/sandbox.md) |
| 权限及已知风险自评 | [安全自评](security-assessment.md) |
| 源码与说明 | [根 README](../../README.md)、apps/api、apps/web、packages/api-client |
| 部署与数据库升级 | [setup.md](../development/setup.md)，当前版本与迁移以文档导航为准 |
| 测试与演示 | [自动测试](../development/testing.md)、[演示验收](acceptance.md) |
| 第三方组件 | [依赖与来源说明](third-party.md) |

## 本地交付范围

按作者当前要求先完成本地版本，暂不配置或发布 GitHub 仓库。正式参赛时还须由作者提供仓库地址与评审访问方式，并在报名系统提交作品名称、简介及团队信息。这里不代签独立创作、法律或知识产权声明。

作品以合成账户和模拟银行演示业务；TOTP 是实际认证器算法，真实银行、真实 IdP 以及短信、人脸和 U盾渠道并未接通。卡片管理、手机号转账、生日订花蛋糕等扩展示例未实现，不属于本次四个核心场景交付范围。

当前默认环境码不能视作真实多因子认证；已实现的安全控制及验收边界见[安全自评](security-assessment.md)。
