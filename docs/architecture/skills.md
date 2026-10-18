# Agent Skills

## 包与业务绑定

应用从可信内置目录加载八个标准 Agent Skills 包，覆盖所有已登记业务 Agent。每个包含 `SKILL.md`，按场景加载 references；三个 Python 业务绑定另提供 `scripts/run.py`。格式遵循 [Agent Skills Specification](https://agentskills.io/specification)；业务 schema、契约版本及权限绑定属于本应用约定。

| 包 | 使用位置 | 执行方式 |
| --- | --- | --- |
| banking-assistance | PersonalBanking ACCOUNT／COMBINED | 账户、余额、账单及收款人只读指令 |
| financial-analysis | PersonalBanking SPENDING／COMBINED | 消费分析，报告模式额外读取 report-source.md |
| subscription-analysis | SubscriptionAnalysisAgent | 订阅成本和续费只读指令 |
| wealth-advisory | WealthAdvisorAgent、HTTP 分析 | 推荐、比较、定位、知识等模式按需激活 |
| wealth-trade-assistance | 理财交易准备 | 补全和解释，提交交由确定性 Workflow |
| monthly-spending-report | MonthlySpendingReportSkill／SkillExecutor | Python 计算报告核心，模型草稿先校验，发布由核心事实确定性生成的解释 |
| transaction-anomaly-analysis | TransactionAnomalyAnalysisSkill | Python 组织已核验异常快照或简短核对提示 |
| wealth-recommendation | WealthRecommendationSkill | Python 将 WealthAnalysis 转为呈现 DTO，供确定性展示和降级 |

Skill 资源版本与应用版本独立；准确值来自各包 YAML metadata，不应作为网页版本。三个 Python 绑定保留稳定业务 ID、类型和整数契约版本。SkillExecutor 专门负责报告草稿校验与确定性解释，其余确定性实现由业务服务调用。

## 发现、激活与权限

AgentSkillCatalog 安全解析 YAML，校验目录名与 name、非空描述、字段类型、metadata 及声明资源，拒绝重复键、未知字段、路径穿越和越界 symlink。元数据用于发现；模型只收到激活技能正文和本次需要的 references。脚本被登记和 hash，不因此授予模型 Shell 执行权限。

应用只读取随应用打包的可信目录，不扫描个人技能目录。`packaged_catalog()` 保存一致的进程快照，正文、版本与资源 hash 来自同一份内容。更新资源后重启 API，避免新旧文本混用。

AgentRegistry 验证技能绑定、指令与 hash；SkillRegistry 验证业务 ID、输入／输出 schema、契约版本及工具权限。Manual 和 LangGraph 执行前重新核验绑定，动态报告和理财模式保留实际激活元数据。`agent.run.started` 等执行事件记录技能版本及资源 hash。

用户显式选择 `$skill-name` 时仍须与已解析动作兼容。未知或不兼容的选择返回明确业务错误，不创建资金工作流，也不能用技能覆盖工具白名单。知识和产品文档只是证据，不是可执行指令。

## Python 入口

三个包的 `scripts/run.py` 通过 stdin 接受 JSON、stdout 输出 JSON；输入错误写 stderr 并以 2 退出。需要 Python 3.12+ 和已安装的 banking-api 包。

- 消费报告 CLI 仅返回确定性核心，不调用模型；应用 SkillExecutor 校验模型草稿，并从核心事实生成客户可见解释。
- 异常 CLI 默认完整说明，`--review` 返回简短 SpendingReview；不重新检测交易。
- 理财 CLI 返回客户 DTO；不改测评、授权、账本或交易状态。

三个入口不写数据库、不执行金融交易。不要把 Python 绑定类单独当作标准技能包，也不要把技能权限当作 Workflow 授权。

## 维护与验证

修改指令或资源时提升对应资源版本，保持业务绑定契约一致；需要改变 schema 时同步实现、注册和调用方。参考文件必须在本包内、可发现且按需加载，不保留未声明的备用提示词。

运行 `test_agent_skill_catalog.py`、`test_standard_skill_bindings.py` 及受影响业务测试，检查安全解析、越界拒绝、三种个人银行配置、两个运行时、资源 hash 和 CLI 实际输入输出。发行 wheel／镜像需包含声明的全部资源，并在安装后发现及激活全部八个包。具体命令见 [测试](../development/testing.md)。

有限模型样本与格式验证不能证明任意正文完全正确。金融计算、事实校验、有限修复、确定性降级及确认／强验证继续由应用控制。历史输出枚举或旧 Task ID 的读取兼容，不表示旧执行器或旧提示词仍在运行。

源码入口：[Agent Skills 包](../../apps/api/src/banking_api/agent_skills/README.md)、[Python 绑定](../../apps/api/src/banking_api/skills/README.md)、[AgentRegistry](../../apps/api/src/banking_api/registries/agent_registry.py)、[SkillRegistry](../../apps/api/src/banking_api/registries/skill_registry.py)。
