# 金融计算与计划约束

## 金融事实

所有金额用 Python `Decimal`。JSON 中保留精确金额字符串；前端读取后端 `*_display`，不自行求和、换算币种、计算占比或判断业务成功。

消费仅统计 `POSTED + DEBIT + category != TRANSFER`；收入仅统计 `POSTED + CREDIT + category != TRANSFER`。待入账、撤销和转账不混入消费与收入。聚合出现多个币种时拒绝混算，不做 FX；订阅成本可按币种分别组织。

期间使用左闭右开区间。自然月、自然年与最近 N 天共享明确的业务参考时间；最近 N 天与紧邻的等长前期比较，月度与年度分别采用环比和同比。工具期间参数互斥，账户与 Principal 范围保持一致。历史查询结果不等于实时余额。

Financial Tools 提供消费汇总、分类、期间比较和主要交易。模型接收聚合与有界明细，不接收整段原始流水来自己计算。Report core 来源于 FinancialAnalysisSnapshot，模型说明需通过既有校验；没有逐句验证所有解释。

## 异常与订阅识别

异常规则为金额突增、短时重复、新商户大额、订阅涨价。每笔交易使用此前 90 天的比较基线，优先同商户同分类（至少 3 笔），再使用同分类（至少 8 笔）。已证实的按月同商户支出按自身历史比较，涨幅至少 30% 才提示，避免稳定房租与小额餐饮混比。

完整异常查询最长一个日历年，明细最多 50 笔并注明截断。消费汇总在同期间、同账户、同用户范围自动生成最多 3 笔优先核对提示；明确拒绝检查时不执行。主动调用完整异常工具要求本次用户明确请求。历史不足与未检出不能解释为安全保证。

订阅检测按商户、币种及固定月度／年度 cadence 组织周期支出，结合 fixture alias 与合同状态区分可管理合同和仅检测项。只有当前可管理合同支持站内取消或恢复；检测结果不代表用户真正使用某项服务。

## 授权、幂等与恢复

转账确认绑定 canonical payload hash。修改账户、收款人、金额、备注或预约范围使原确认和强验证失效。提交再次核对权限、状态、风险、安全锁、授权与有效余额。

Mock Provider 用账户级 PostgreSQL advisory lock 串行化余额决策，账本原子保存接受结果；用户级锁保护风险 exposure 和安全控制。幂等键关联既有 Operation，UNKNOWN 查询该操作，不另建扣款。预约期次和订阅扣费账期同样具有持久化唯一性与去重证据。

Task、Operation、Outbox 与 Schedule 使用各自持久化领取和恢复机制。Task heartbeat 与 attempt fencing 防止过期执行者覆盖新尝试，LangGraph checkpoint 不代替业务租约。

## 受约束计划

Planner 只选择已注册的账户、消费、订阅分析及转账／订阅管理能力。固定 DAG 最多 8 步、2 个 CONDITION、一个写 Workflow，ready steps 按 ordinal 推进。没有 ELSE、嵌套条件、任意表达式、AND/OR、循环、多写业务或动态重规划。

条件只使用预注册 Predicate 和可信源结果；阈值必须由原始请求中对应条件从句明确给出，并作为 Decimal 字符串保存。不能把动作中的转账金额当阈值，也不能把“余额够”“花费太多”自行解释成金额。币种须有原文依据或满足可信源的唯一币种规则。

条件为 FALSE 时跳过受保护步骤，不创建写业务。TRUE 也不替代确认和强验证。写 Workflow 从原始 Message 提取意图，继续受既有控制约束。复杂计划暂未注册 Report Artifact 生成能力；单独分析并生成报告仍走 Financial Agent。

相关源码：[financial](../../apps/api/src/banking_api/financial/analytics_service.py)、[异常检测](../../apps/api/src/banking_api/financial/anomaly_detector.py)、[订阅检测](../../apps/api/src/banking_api/subscriptions/detector.py)、[条件 grounding](../../apps/api/src/banking_api/planning/threshold_grounding.py)、[计划验证](../../apps/api/src/banking_api/planning/validator.py)。
