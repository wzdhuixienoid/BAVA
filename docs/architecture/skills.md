# Skill 使用与审计（2026-10-13）

当前应用交付版本：**0.11.2**；Skill 资源版本 **0.12.3** 独立管理，不能作为应用版本显示。

## 当前统一的标准技能结构

本项目现在有 **8 个标准 Agent Skills 包**，覆盖所有 **4 个已注册业务 agent**。原来的 3 个 Python 业务 Skill 是其中三个标准包的绑定实现；每个包包含 `SKILL.md`、需要时加载的 references 或可运行的 `scripts/run.py`。

目录名、YAML name/description、metadata 和相对引用按照 [Agent Skills Specification](https://agentskills.io/specification) 校验。metadata.version、业务 ID、输入输出 schema 和契约版本是应用绑定约定。权限白名单与金融执行始终由代码和原有 Policy/Workflow 决定。

| 标准技能包 | 实际调用与执行方式 |
| --- | --- |
| banking-assistance | MinimalBankingAgent 从包加载只读账户/收款人查询指令；Manual 与 LangGraph 使用相同绑定。 |
| financial-analysis | FinancialAnalysisAgent 加载消费分析指令；报告采集额外加载 report-source.md，继续使用受限银行聚合工具。 |
| subscription-analysis | SubscriptionAnalysisAgent 加载订阅分析指令，仅拥有 subscription.analyze 权限。 |
| wealth-advisory | 对话与 HTTP 理财分析按推荐、比较、定位或知识模式激活技能，模型说明经事实/证据/关系校验后展示。 |
| wealth-trade-assistance | 对话交易准备进入确定性 Workflow；HTTP 分析可以生成只读准备说明，不通过技能直接提交交易。 |
| monthly-spending-report | Python 构建消费快照的报告核心，SkillExecutor 使用包内指令生成和校验文字，tools=[]；CLI 只输出核心。 |
| transaction-anomaly-analysis | Python 根据异常快照生成完整说明或简短核对提示；CLI 默认完整说明，--review 输出 SpendingReview。 |
| wealth-recommendation | Python 将已校验 WealthAnalysis 转为客户 DTO，供确定性呈现与模型降级使用；CLI 输入分析 JSON，输出 DTO。 |

三个业务 Python 模块保留稳定模块导入路径、业务 ID 和整数契约版本，绑定的标准技能资源版本为 0.12.3。SkillExecutor 的执行职责仍为报告生成；其他确定性实现由对应业务服务调用。

注册时会校验标准包、指令/资源 hash 以及输入输出契约，拒绝只有自由提示词或契约错配的实现。Manual 与 LangGraph 在运行前再次校验绑定，不能绕过注册表直接运行无技能的 agent。运行时记录所加载的技能版本与资源 hash；派生的报告采集、理财答复和金融查询范围限制保留绑定元数据。计算、确认、强验证和交易状态机保持原有后端职责。

## 第一轮审计修复（保留记录）

1. **加载器不是 YAML 解析器。** 正则会接受重复 name、空白描述等无效元数据，也不能正确处理合法引号与多行描述。改为安全 YAML 解析，拒绝重复键、未知字段、无效字段类型及无效 metadata；显式声明 PyYAML 依赖。
2. **显式技能可改变当前模式。** `$wealth-trade-assistance` 原本能覆盖推荐动作，反向错配也成立；未知技能会触发内部任务失败或 HTTP 500。现在检查与已解析动作的兼容性，HTTP 返回 422 `INVALID_SKILL_SELECTION`，对话以明确说明完成，不创建金融工作流。
3. **资源不可发现及 hash 不一致。** product-overview.md 已按定位模式加载，却没有从 SKILL.md 链接。补上链接，并在发现时检查参考文件。SKILL.md 的正文、版本与 hash 来自同一个加载快照，避免文件更新后旧指令与新 hash 混用。WealthAnswer 增加默认空的 skill_resource_hashes，旧消息仍可读取。
4. **异常 Skill 未登记。** 补全 SkillRegistry，实际运行清单现在与定义一致。
5. **赎回被当作申购。** 降级答复会问申购金额/付款账户，分析服务还会要求购买测评，继承的保本偏好也可能错误阻止赎回。现在使用份额/本人持仓账户，不把预算当作份额，不重新要求申购测评；是否可赎回仍交给原有持仓与工作流校验。
6. **交易模型重复询问已知字段。** 给模型提供已核验的 trade_fields，并让最终交易追问来自确定性缺失字段。已提供的产品、账户和精确数量只核对，不重复收集。
7. **真实模型比较引用格式错误。** 模型复制带 subject/object 的关系对象，有限修复后仍降级。明确 relations 的 ID 字符串数组契约，提供 allowed_relation_ids，改进格式错误说明；未放宽事实和比较关系验证。
8. **消费报告 smoke 脚本过时。** 新增默认字段使历史 golden JSON 的直接字典比较失败，脚本在调用模型前即中断。通过当前报告 schema 解析历史基准，补全默认字段，同时继续逐字段核对全部报告数值。

第一轮修复将两个包更新为 0.12.1；统一结构时为 0.12.2，本轮清理后的八个技能资源版本为 0.12.3，业务契约版本保持 1。

## 遗留实现清理与交互复查

- 删除旧段落重排 `organization_prompt` / `apply_organization` 及其专用 `smoke_wealth_advisor.py`，旧契约测试改为验证当前正文契约的拒绝与降级。当前模型评估脚本仍使用原语义数据集文件名，实际调用当前标准技能和正文入口。
- 删除未使用的月报提示词常量以及空的 `WealthRecommendationSkill` 兼容包装层。当前仅有一个 `WealthRecommendationSkill` 实现，分析呈现、正文降级、注册表与 CLI 均使用它。
- 理财 HTTP、对话执行和模型评估统一使用 `packaged_catalog()`。SKILL.md、references 与脚本 hash 来自同一份进程快照；资源在进程运行期间改变不会混用新旧内容，重启后整体加载新包。
- 消除赎回答复中继承投资预算产生的金额展示，以及对已知账户的重复选择提示。交易准备因测评阻断或申请已提交而回滚时，实际技能及失败状态与最终用户答复一起持久化。
- 逐包检查所有文件均已声明、相对引用可读且位于本包内；八个包无未引用的遗留资源。标准格式验证、安装后的 wheel 和运行容器均核验完整资源与绑定。

历史已保存快照仍可能带 `MODEL_ORGANIZED` / `FALLBACK`，因此只保留数据枚举的读取兼容；当前执行路径不再生成旧重排契约。历史发布记录继续保留当时的验证结果。

## 统一结构的验证

- 全部八个包通过 quick_validate。Catalog 验证相对引用存在且不越界，并对实际加载的 Markdown 和 Python 入口记录 hash。
- 新增回归实际运行四个业务 agent，检查模型请求中包含包内指令、事件记录相同资源 hash；覆盖 Manual 与 LangGraph、报告派生模式，以及未绑定/伪造指令/契约不匹配时的注册拒绝。
- 三个 Python 入口均使用真实快照执行，检查消费报告 golden 金额、异常交易证据与简短核对、赎回单位及已知字段；不完整 JSON 被拒绝且不会产生业务输出。
- 本轮完整 API 回归：1020 passed、18 skipped；另在新建隔离 PostgreSQL 库运行 53 项集成测试，全部通过。前端 110 项交互回归通过。141 项针对性检查包括公开消息 API→生产路由/工具→技能→可读取答复或补全卡片。
- 当前配置的真实模型完成七条完整消息路径：账户与余额、订阅、消费报告、异常分析、推荐、比较、赎回补全。六条任务 COMPLETED，赎回为 WAITING_USER；无金融 Operation。推荐样本正文核验触发确定性降级，比较为 MODEL_GENERATED；赎回正常显示缺失份额并等待用户。任务完成并不等于全部样本正文由模型生成。
- 前一轮独立模型抽样消费报告 golden_core_equal=True、tool_calls=0，推荐、比较、赎回说明为 MODEL_GENERATED；保留该历史结果，与本轮完整用户消息链路分开统计。
- 发行 wheel 的全部 21 个技能相关文件与源文件逐字节相符；安装后校验八个包与四个 agent。部署容器校验八个包 0.12.3、四个 agent、三个业务契约、资源 hash 及旧符号已不存在。

格式校验与有限模型样本不证明任意自由文字的全部语义。原有金融事实校验、工具权限、有限修复、确定性降级与本人工作流边界继续生效。
