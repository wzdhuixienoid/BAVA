# WealthAdvisorAgent

## 职责与入口

`agent:wealth-advisor` 提供模拟理财目录、推荐、比较、策略定位、资料问答、本人持仓与订单解释。只在 development／test 装配登记，production 不登记；关闭新业务开关仍保留只读查询和已受理订单恢复。

WEALTH_ANALYSIS 路由及理财中心发起的推荐／比较进入工作台；对话的 WealthIntentFrame 先解析本次动作、数量和产品指代。HTTP 分析共用事实与正文服务，不等于每次页面读取都运行 Agent。

## Skill 与工具

默认绑定 wealth-advisory 及 agent-rules.md、evidence-and-facts.md，按目录、推荐、比较、定位和知识模式加载所需 references。交易准备可以激活 wealth-trade-assistance；它仅协助补全及解释，不授予申赎提交权。

| 能力 | 只读事实 |
| --- | --- |
| `wealth.list_products` | 当前目录与本人资格 |
| `wealth.get_product` | 单品版本、风险、费用及条款 |
| `wealth.compare_products` | 最多四款产品的客观事实及比较 |
| `wealth.recommend` | 测评和本次硬条件内的候选 |
| `wealth.search_knowledge` | 有效资料、历史订单原版本与证据 |
| `wealth.list_positions` | 本人已确认持仓及可赎回份额 |
| `wealth.get_orders` | 本人申请／订单状态，不推进成交或到账 |

以上七项均为 R1；每次分析可进一步缩小范围。wealth-recommendation 的 Python 绑定把校验后的分析转成客户 DTO，供确定性呈现与降级，不是第四个 Agent。

## 执行与结果

WealthAdvisoryService 先计算适当性、约束、候选、费用、到账链路、事实和证据；LangGraph 通过受控工具取得事实，模型生成带引用的正文。关键数字、关系、版本、作用域及资格核验失败最多修复一次，再用同一事实确定性降级，不重新执行金融业务。

Task.output 保存 wealth_analysis，包含请求、顺序、证据／测评版本、参考时间及 WealthAnswer。后续追问只读取本人本对话已完成分析的精简上下文，按 SET／CLEAR／KEEP 更新需求；“第一款”等按实际保存顺序解释。历史快照不随刷新重算，新对话不继承旧预算或候选。

购买意向可先进入只读选购，明确产品／本人账户／数量后才通过 Workflow API 创建核对草稿；口头完成测评须重新读取实际记录。申购／赎回分别交给确定性 WealthWorkflow 和 WealthExecutionEngine。

## 边界与失败处理

没有申赎提交、对账、修改测评或任意网络／SQL 权限。缺失测评可看目录和客观比较，不能个性化推荐或新申购；赎回不因测评下降被阻止。C5 不代表本次想买高风险，保本／拒绝损失／即时用款条件不为凑候选而放宽。

通用教育、Mock 条款和模拟 DESIGN 画像分开；画像不是实际持仓或收益预测。资料 hash／版本冲突时拒绝引用或新申购，已受理订单仍使用原条款。没有证据、指代不唯一、数量／单位矛盾时明确补充，不编造结论。

推荐和申请受理不是交易授权或金融成功。新业务暂停时不能新建测评、授权或首次受理，但原订单与 UNKNOWN 继续恢复；恢复由 Worker／Workflow 执行，Agent 的只读 GET 不推进结算。

## 源码与验证

[定义](../../../apps/api/src/banking_api/agents/wealth_advisor_agent.py)、[七项查询](../../../apps/api/src/banking_api/wealth/tools.py)、[分析服务](../../../apps/api/src/banking_api/wealth/advisory.py)、[正文校验](../../../apps/api/src/banking_api/wealth/answer.py)、[知识维护](../../../apps/api/src/banking_api/knowledge/README.md)。

验证入口：test_wealth_advisory.py、test_wealth_strategy.py、test_wealth_v0113.py、标准绑定与安全回归；真实模型使用授权的纯合成数据独立评估。用法见 [理财指南](../../guides/wealth.md)，命令见 [测试](../../development/testing.md)。
