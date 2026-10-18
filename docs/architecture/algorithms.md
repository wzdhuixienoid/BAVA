# 金融计算与跨层规则

## 金融事实

所有金额用 Python `Decimal`。JSON 中保留精确金额字符串；前端读取后端 `*_display`，不自行求和、换算币种、计算占比或判断业务成功。

消费投影先排除理财来源的资产现金移动，再统计 `POSTED + DEBIT + category != TRANSFER`；收入仅统计 `POSTED + CREDIT + category != TRANSFER`。待入账、撤销和转账不混入消费与收入。聚合出现多个币种时拒绝混算，不做 FX；订阅成本可按币种分别组织。

期间使用左闭右开区间。自然月、自然年与最近 N 天共享明确的业务参考时间；最近 N 天与紧邻的等长前期比较，月度与年度分别采用环比和同比。工具期间参数互斥，账户与 Principal 范围保持一致。历史查询结果不等于实时余额。

Financial Tools 提供消费汇总、分类、期间比较和主要交易。模型接收聚合与有界明细，不接收整段原始流水来自己计算。Report core 来源于 FinancialAnalysisSnapshot；报告模型草稿经结构化校验后，客户可见标题、最高消费分类及期间变化解释仍由可信core确定性生成，不直接发布草稿自由文本。理财正文使用另行限定的事实引用校验，不能视作通用语义证明。

## 异常与订阅识别

异常规则为金额突增、短时重复、新商户大额、订阅涨价。每笔交易使用此前 90 天的比较基线，优先同商户同分类（至少 3 笔），再使用同分类（至少 8 笔）。已证实的按月同商户支出按自身历史比较，涨幅至少 30% 才提示，避免稳定房租与小额餐饮混比。

完整异常查询最长一个日历年，明细最多 50 笔并注明截断。消费汇总在同期间、同账户、同用户范围自动生成最多 3 笔优先核对提示；明确拒绝检查时不执行。主动调用完整异常工具要求本次用户明确请求。历史不足与未检出不能解释为安全保证。

后台 AnomalyNotificationWorker 直接复用检测器和已入账投影，扫描各账户所有者近30天记录，使用90天历史基准。重复扣款按账户、商户、币种、金额分组。工具展示仍最多50笔；后台继续分页取得全部命中，按用户和交易的稳定唯一键保存一条通知。已读、删除、重启、多进程均不会重复生成同一笔提醒；详情保留生成时的证据，无模型调用或金融写操作。

订阅检测按商户、币种及固定月度／年度 cadence 组织周期支出，结合 fixture alias 与合同状态区分可管理合同和仅检测项。只有当前可管理合同支持站内取消或恢复；检测结果不代表用户真正使用某项服务。

## 授权、幂等与恢复

转账确认绑定 canonical payload hash。修改账户、收款人、金额、备注或预约范围使原确认和强验证失效。提交再次核对权限、状态、风险、安全锁、授权与有效余额。即时转账仅在单笔严格小于本人免密额度（默认200元、上限200元）且日累计成功及执行中风险暴露含本笔≤1000元时为黄色；否则为红色。个人额度修改需要强验证，提交时读取最新设置。

Mock Provider 用账户级 PostgreSQL advisory lock 串行化余额决策，账本原子保存接受结果；用户级锁保护风险 exposure 和安全控制。幂等键关联既有 Operation，UNKNOWN 查询该操作，不另建扣款。预约期次和订阅扣费账期同样具有持久化唯一性与去重证据。

Task、Operation、Outbox 与 Schedule 使用各自持久化领取和恢复机制。Task heartbeat 与 attempt fencing 防止过期执行者覆盖新尝试，LangGraph checkpoint 不代替业务租约。

## 条件计算与计划约束

Planner 只选择已注册的账户、消费、订阅分析及转账／订阅管理能力。固定 DAG 最多 8 步、2 个 CONDITION、一个写 Workflow，ready steps 按 ordinal 推进。没有 ELSE、嵌套条件、任意表达式、AND/OR、循环、多写业务或动态重规划。

条件只使用预注册 Predicate 和可信源结果；阈值必须由原始请求中对应条件从句明确给出，并作为 Decimal 字符串保存。不能把动作中的转账金额当阈值，也不能把“余额够”“花费太多”自行解释成金额。币种须有原文依据或满足可信源的唯一币种规则。

条件为 FALSE 时跳过受保护步骤，不创建写业务。TRUE 也不替代确认和强验证。写 Workflow 从原始 Message 提取意图，继续受既有控制约束。复杂计划暂未注册 Report Artifact 生成能力；单独分析并生成报告由 PersonalBankingAgent 的消费配置执行。

手动接管暂停自动编排，不撤销已提交 Operation。回退仅允许目标及全部后继为只读／条件步骤，且没有关联工作流；不提供金融交易撤销。编排职责见 [Plan 架构](plans.md)，用户操作见 [多步骤任务](../guides/plans.md)。

相关源码：[financial](../../apps/api/src/banking_api/financial/analytics_service.py)、[异常检测](../../apps/api/src/banking_api/financial/anomaly_detector.py)、[订阅检测](../../apps/api/src/banking_api/subscriptions/detector.py)、[条件 grounding](../../apps/api/src/banking_api/planning/threshold_grounding.py)、[计划验证](../../apps/api/src/banking_api/planning/validator.py)。
