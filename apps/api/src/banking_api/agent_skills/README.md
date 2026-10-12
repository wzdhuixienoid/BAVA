# 应用 Agent Skills（v0.11.4）

遵循 [Agent Skills 规范](https://agentskills.io/specification) 的可信应用包，区别于 Codex 个人技能和 Python 业务方法。

两个目录均含 YAML name/description 和 metadata.version，目录名与 name 相同。wealth-advisory 按推荐、比较或知识模式加载 references；wealth-trade-assistance 仅加载交易输入与 Workflow 规则。发现只提供元数据，激活后按需加载正文与参考文件。

修改资源时审阅权限和业务约束、更新版本，运行 test_wealth_v0113 与真实模型评估。事件记录 skill_id/version/resource_hashes、激活和完成或失败。镜像检查 discover/activate 确认资源随包部署。加载器只接受当前可信包使用的 YAML 标量子集，不是任意第三方插件加载器；没有脚本、Shell、SQL 或网络权限。工具权限仍由应用 Policy 决定。

定位模式独立加载 product-overview.md；推荐和比较按模拟设计画像解释策略与风险，事实引用不扩大工具和交易权限。
