# 赛题需求覆盖与 Bug 评估

基准：v0.9.2，Git `667dd9e`，2026-10-05。依据 README、版本交付文档、12 个项目 Codex 对话、当前源码及本轮隔离回归。状态表示当前代码实际能力，不沿用历史版本的完成标记。

## 1. 总体判断

**按“至少三个场景方向”的口径，已具备智能转账、账单分析、订阅管理三条可演示链路；按题目全部典型能力和严格技术要求的口径，尚未全满足。** 是否达到比赛最终验收标准，还取决于评委是否认可 Mock Provider / Mock MFA，以及对代码沙箱、渠道接入的要求。

长处是金融事实、授权、风险和写入边界：LLM 不决定余额、条件结果、风险等级或业务成功；应用以 Workflow、Approval、Reauthentication、Operation、Provider ledger 的结构化状态执行。主要缺口是理财/卡片、定时与 AA、生日场景、真实强验证、主动提醒、代码沙箱及更完整的上下文理解。

**当前存在 Bug。** 本轮复现了三类新问题，不能继续无条件宣称“条件永不遗漏”“未知币种必定拒绝”或“所有验证码失败都会计入熔断”。现有确认、强验证、权限与 Provider 保护仍然存在，本轮没有发现或证明绕过这些控制后直接扣款。

## 2. 场景逐项对照

| 赛题需求 | 当前状态 | 已实现与缺口 | 主要证据 |
|---|---|---|---|
| 自然语言理解、规划并执行银行业务 | 已实现受约束链路 | 中文文本→Router→Agent/Workflow/Plan；写入需用户操作。不支持自由生成任意业务执行方案 | `routing/`、`runtime/task_runner.py`、`application/plan_execution_service.py` |
| APP、IM 等渠道联通 | 部分实现 | 有 Next.js Web 与 HTTP/SSE API；未实现手机原生 APP、IM 接入、语音 ASR/TTS、多模态输入 | `apps/web/`、`api/routes/` |
| 姓名转账 | 已实现 | 同名消歧、选择账户、金额/余额校验、确认、强验证、提交、恢复 | `workflows/transfer/` |
| 手机号/备注转账 | 部分实现 | 支持 fixture 的**手机尾号别名精确匹配**，不是任意完整手机号或任意备注匹配；无收款人新增流程 | `mock_bank/service.py::search_payees`、`mock_bank/data/payees.json` |
| 定时转账、AA 拆分收款 | 未实现 | 无预约日期/定时支付模型、业务调度器、AA/收款能力；Task/Recovery 定时扫描不能充当这些能力 | 转账 schema 只有收款查询、金额、币种、账户提示 |
| 消费分类统计、环比、Top N | 已实现 | 对已有交易分类做确定性汇总；不是 LLM 对任意流水重新分类 | `financial/analytics_service.py` |
| 异常交易识别 | 已实现有限规则 | 四类可解释规则、证据与基线；无欺诈 ML、人工审核平台或欺诈结论 | `financial/anomaly_detector.py` |
| 月度/年度账单报告 | 部分实现 | 月度 Snapshot→Skill→持久 Report→UI 完整；年度报告/PDF/导出接口未实现 | `skills/monthly_spending_report.py`、`application/report_service.py` |
| 理财推荐、对比、风险评估、申购/赎回 | 未实现 | 无对应 Agent、Workflow、Tool、产品数据和适当性流程 | 当前 Registry/PlanCapability 枚举 |
| 卡申请、额度、限制/解锁、挂失/解挂 | 未实现 | 账户列表中存在信用卡不等于实现卡片管理；没有卡写操作流程 | 同上 |
| 识别订阅、涨价、续费提示 | 部分实现 | 有周期识别、按币种成本、涨价、即将续费列表；无后台主动推送/到时通知。过期 fixture 日期不会自动滚动 | `subscriptions/detector.py`、`subscriptions/service.py` |
| 取消订阅 | 已实现可管理合同范围 | MANAGED + ACTIVE + cancellable→YELLOW→Approval→Operation→Mock Provider；DETECTED_ONLY 不可取消；无真实商户 API | `workflows/subscription_cancel/` |
| 跨场景联动 | 部分实现 | 余额/消费/订阅查询 + 条件 + **一个写 Workflow**；不支持生日识别、资金锁定、鲜花蛋糕下单、提前两天调度 | `planning/`、`application/plan_execution_service.py` |

场景示例被题目注明“仅作参考”，不能把缺少一个示例直接等同于该方向完全不合格；也不能用实现一个方向的基础能力宣称该方向所有示例 COMPLETE。

## 3. 核心技术逐项对照

| 要求 | 判断 | 当前保证与实际边界 |
|---|---|---|
| GREEN 自动查询 | 基本满足 | 账户、消费、报告数据、订阅和异常查询自动执行；有 Principal ownership 和只读 Tool Policy |
| YELLOW 小额确认 | 满足当前 CNY 转账/取消范围 | 当日成功 + 执行中 + 本笔 ≤1000 CNY 需 Approval；取消订阅固定 YELLOW。不是只看本笔金额 |
| RED 强验证 | 流程已实现，真实验证未满足 | >1000 CNY 需 Approval + payload 绑定的 Reauthentication；目前固定 Mock code，未接人脸、SMS、U盾等真实因子。密码、挂失、理财等 RED 业务未实现 |
| 幻觉防护 | 关键事实有强约束，解释部分有边界 | typed balance/display、Decimal、报告证据校验、Workflow+Operation 双成功；普通自然语言仍可能错误，无逐句语义蕴含校验 |
| 注入防御 | 执行权限边界已实现 | Default Deny、Tool allowlist、严格 schema、服务端身份、Action gates。模型可受文本影响；R02/R03 说明意图语义校验还存在缺口 |
| 操作审计 | 基本满足原型审计 | Event+Outbox、风险/授权/hash/Guard/条件/Provider 历史、owner-scoped Audit UI；上限1000事件、旧证据不补造，无数据库防篡改签名链/WORM |
| 异常熔断 | 已实现明确安全信号，存在 R01 边界 Bug | 3次验证失败/10分钟或5次绕过/5分钟→写锁15分钟；普通业务失败、Provider超时及交易异常不会触发锁 |
| 生成代码在受限沙箱运行 | 未实现代码执行沙箱 | Agent 仅调用开发者预定义工具，没有模型生成代码执行入口，避开了该风险路径。Docker、Tool allowlist、Mock 银行环境不能代替完整代码 Sandbox |
| 模糊、省略、隐含意图 | 部分实现 | Agent 可收到最近10条 USER/ASSISTANT；Router、Planner、转账提取主要使用当前原始消息，缺少统一上下文消歧/澄清状态。模糊条件拒绝而非猜金额；R02 为常见句式遗漏 |
| 有序 DAG | 已实现受约束 DAG | 固定持久图，最多8步、2条件、1写；稳定序号执行 ready steps，无多写、循环、ELSE、动态重规划 |
| 中断、回退、人工接管 | 部分满足 | Plan 接管暂停+fencing、resume、只读步骤及下游回退；无 Plan cancel API，无法撤销已成功金融副作用；不等同于完整人工银行审核台 |

题目表格把“订阅查询/取消”列入黄色，同时总原则把纯查询列为绿色。当前实现选择“订阅查询绿色、取消黄色”，符合总原则；若评委严格要求订阅查询也确认，则需调整该策略并说明理由。

## 4. 本轮确认的问题

优先级：P1=建议比赛演示前修复的语义安全缺口；P2=可靠性/健壮性问题。复现脚本见 `report/verification/test_review_repros.py`，使用 FakeLLM/隔离 SQLite，不依赖当前真实模型随机表现。

### R01 / P2：非 ASCII 验证码返回 500，失败不进入熔断计数

**步骤：**隔离环境创建2000元 RED Workflow，完成 Approval、开始 Mock challenge；连续三次向 verify-reauth 传入 `错误验证码`。

**实际：**三次 HTTP 500；challenge.attempt_count 仍为0，没有累计验证失败写锁。**预期：**返回受控的验证失败或输入错误；对于被接受为验证尝试的输入，按明确策略记录失败，不抛服务器异常。

**根因：**`security/reauthentication/mock_provider.py:28` 对 Python str 直接调用 `hmac.compare_digest`，非 ASCII str 会抛 TypeError；`application/workflow_service.py:559` 尚未进入失败记录，HTTP route 也没有捕获此异常。

**影响：**中文粘贴、全角字符等可使验证页面出现服务器错误，失败审计和计数遗漏。没有证明认证通过或资金提交。

**建议：**规定验证码字符集/长度，或对双方统一 UTF-8 bytes 后常量时间比较；把错误转成稳定领域结果，并覆盖中文、全角、emoji 和不合法配置的测试。

### R02 / P1：常见“只有……才……”条件可通过无条件计划校验

**输入：**`只有工资卡余额不少于30000元，才从工资卡给李小雨转500元。`

**复现方式：**Fake Planner 返回两步“查余额→转账”，省略 CONDITION 与 guard；通过真正的 `ConstrainedPlanner.propose` 和 `PlanValidator`。

**实际：**提案被接受；同一错误提案配 `如果……` 则被拒绝。初始工资卡23864.52低于30000，正确语义本应跳过转账分支。

**根因：**`planning/constraints.py:4` 的条件关键字正则未覆盖“只有/只要/才/当……时”；`planning/validator.py:138` 仅在该函数返回真时强制条件与写 guard，grounding 同样依赖有限句式识别。

**影响与证据边界：**已证明后端能接受丢失用户条件的写计划，尚未在本轮执行该计划到 Workflow/Provider，也未证明真实 LLM 对该句每次省略条件。Approval/RED验证不会被此问题取消，但用户有条件意图可能丢失。

**建议：**把条件意图识别与可支持语法校验分开；疑似条件但不能确定解析时 fail closed/澄清。扩展同义句式回归，并验证“模型省略 CONDITION、漏 guard”均拒绝。

### R03 / P1：未识别币种可在模型漏填时变为 CNY 转账草稿

**输入：**`从工资卡给李小雨转500瑞士法郎。` 或 `从工资卡给李小雨转$500。`

**复现方式：**Fake extractor 返回500、工资卡、李小雨、currency=null；运行真实 TransferIntentExtractor 与 TransferWorkflowEngine。

**实际：**进入 `READY_FOR_REVIEW`，review_payload 为500 CNY。**预期：**未知/歧义货币要求澄清；明确外币须被拒绝或流入外币不支持校验，不能按未写币种默认。

**根因：**`workflows/transfer/currency.py:5` 的别名缺少 `$` 等符号；未知中文单位检测仅覆盖以“币/元/镑”结束的形式，漏掉“法郎”。函数返回None，`workflows/transfer/engine.py` 将其补为付款账户CNY。RiskPolicy只看到已变成CNY的草稿，不能恢复原文币种。

**影响与证据边界：**已证明可形成错误币种的可审批草稿，本轮没有 Approval、Operation 或扣款；真实模型如果正确输出CHF/USD，也可能拒绝请求，不能把 Fake 边界复现写成真实模型必现。

**建议：**补充原文货币标记检测和未知货币词拒绝，将“没有表达币种”与“表达了无法识别的币种”分开；直接 Workflow 与 Plan 写路径都覆盖回归。

### K01 / P2（已知限制）：多 API 进程可能漏实时通知且页面不自动兜底

`runtime/event_bus.py` 的订阅队列仅保存在本进程；某进程的 Outbox publisher 不会通知另一进程的 SSE client。`ConversationPanel.tsx` 仅在事件、连接重建和用户操作时刷新，无周期性资源轮询。页面可持续显示“实时连接正常”但状态不更新。

本轮两个独立 EventBus 实例验证了消息不互通；未部署两个实际 API 进程做浏览器 E2E。单 API Docker Demo 通常不遇到这一情形。README 已披露，建议比赛保持单 API 进程，生产采用跨进程 broker或适度轮询兜底；资金持久状态不受通知丢失影响。

## 5. 不应继续误报为当前 Bug 的历史问题

v0.5.2 的跨进程余额透支、v0.7.3 的 Guard/Operation TOCTOU、v0.8.2 的条件阈值来源、v0.9.1/v0.9.2 的单位规范化与产品事实展示，均已有修复及当前回归证据。R03 是仍未覆盖的货币写法，而非宣称已有CNY/美元回归失效。

LLM服务不可用、严格报告叙述校验拒绝、非CNY拒绝、余额不足、只读回退不能撤销转账，以及固定fixture无数据月份失败，应按设计边界解释，不能一律当成错误。历史报告10次成功也不能证明未来或任意输入零失败。

## 6. 建议完成顺序

1. 修复 R02、R03、R01，并以原文→实际产品路径添加回归；保留既有 Approval/Provider 控制。
2. 答辩把“3个场景方向”“Mock强验证”“只读回退”“无代码执行”讲准确；不要演示不存在的生日、理财、卡片能力。
3. 若继续扩展，先做统一上下文/澄清与显式定时请求拒绝，再按赛题收益选择主动提醒、定时转账、AA或第四场景。
4. 接真实银行前补真实身份因子、Provider协议与账务、运维观测、跨进程通知、审计防篡改和适用的数据保护设计。
