# 历史档案：AI Banking Agent v0.9.2 Implementation Report

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

验证日期：2026-10-05，Asia/Shanghai。源码/API/package 版本：0.9.2。Release verdict：**READY**。自动回归、真实产品 smoke、报告稳定性、S1–S12 浏览器验收及最终 reset / preflight 均已实际通过。

## 1. 版本目标

让评委通过确定性证据了解请求如何路由、谁确认了什么、哪些安全控制生效、Provider 最终确认了什么。Backend decides facts / Frontend renders facts / LLM explains facts。

## 2. Scope Freeze

保留 v0.9.1 账户、消费、报告、订阅、异常、转账及受约束 Plan / Condition 能力。没有新增银行业务、Agent/Planner Capability 或 Condition Predicate。理财、卡片管理、多写 Workflow、ELSE、循环、动态重规划、RAG、MCP、Multi-Agent、长期记忆、FX、真实 Provider/MFA、Kafka/Redis/Celery、任意模型代码执行、通用 Rule Engine 和 Fraud ML：NOT IMPLEMENTED（明确排除范围）。

## 3. Audit Evidence Chain

`GET /api/v1/tasks/{task_id}/audit` 是 authenticated、owner-scoped、只读 Domain resource。先校验 Task 和所属 Conversation 的双重 ownership，其他用户与不存在资源均返回 404；随后读取 owner 相关 Workflow / Approval / Reauthentication / Operation / Plan。

不存储或展示隐藏推理、模型 scratchpad、reasoning token、完整 Prompt、JWT、API key 或 OTP。Message 证据使用原 Message ID，用户原文仍在所属对话中，Audit 不再次复制完整请求/Prompt。

## 4. Audit Data Model / Projection

检查结果：现有 Event 已保留完整 TransferRiskDecision、ConditionDecision、Workflow/Operation 状态转换；Approval 旧行及 invalidated Event 保留历史 hash；UNKNOWN 和最终 Provider 结果都有持久 Event。缺口是授权消费、提交/恢复开始、Guard 新写检查及解析/校验细节。

以现有 Event + Outbox transaction 在原安全边界补记这些事实；`AuditProjection` 聚合历史 Event 和当前资源快照，**无新增表或 migration**。Event.sequence 是数据库分配的全局排序，不要求连续，不依据前端时间重新排序。历史和当前快照明确分开。历史最多取 1000 个 Event、资源最多 100 项，超限显示不完整；不会补造旧版本没记录的证据。

Event 在应用正常业务路径中是 append-only，资源状态是 persisted current state。没有新增数据库不可变约束、签名链或 WORM 存储；DB 管理员与 dev/test reset 能删除历史，不能宣称防数据库管理员篡改。

## 5. Transfer Audit

事件保存用户请求身份、Task、路由、草稿意图、收款人与账户解析、确定性 validation、风险、授权、Guard、commit-time 风险、Operation、授权消费、Provider submit intent、结果及 reconcile。提交意图只证明提交路径开始，不能单独证明网络成功；Provider ledger / final result 才是业务事实。

## 6. Approval Audit

每次授权的 ID、owner、Workflow、created/expires/approved/invalidated/consumed 时间、完整 canonical payload hash、金额/币种/内部业务身份和消费关联均可检查。金额变更保留旧 INVALIDATED 授权和新 hash。TTL 查询信息仅表示查询时是否在有效期内，不替代 commit 的 status/hash/expiry/version 验证。

## 7. Reauthentication Audit

明确显示 Mock Reauthentication、状态、created/expires/verified 时间、失败尝试数、关联 Approval/Workflow。服务使用 constant-time Mock secret 比较，验证码不进入数据库/Event/Audit；安全时钟仍为真实服务器时间。Mock MFA 不代表接入真实银行身份验证。

## 8. Risk Audit

直接使用现有 persisted TransferRiskDecision，含 current amount、successful/in-flight/projected exposure、threshold、business date、decision time 和两个 control requirement。保留首次 YELLOW 与 commit-time RED，原授权不能使升级后的 RED 跳过验证。CNY-only fail closed 保持不变，不做 FX。

## 9. Condition / Plan Audit

保留真实 Plan/Step 的 dependencies、kind、capability、guard、状态和 ConditionDecision source/hash/actual/threshold/currency/outcome/time。FALSE 的 guarded write Step 真实 SKIPPED，projection 从相关资源与 ledger 查询得出 zero Workflow / Approval / Operation / Provider facts；前端没有通过缺失卡片推断。

## 10. Security Guard Audit

记录 NORMAL / WRITE_LOCKED 新写检查，以及失败/绕过 trigger、count、对应窗口、lock time 和 until。验证失败默认 3 次/600 秒，控制绕过默认 5 次/300 秒，锁定默认 900 秒，均可配置。拒绝创建新 Operation 的事实独立持久化；GREEN 查询和已有 Operation recovery 不经过新写 gate。到期按真实时钟惰性恢复，demo reset 仅 dev/test。

## 11. Subscription Audit

解析证据包含 MANAGED/DETECTED_ONLY、merchant、subscription ID 和 cancellable。已可复核 YELLOW、Approval required / Reauthentication not required、hash/consume、Operation、Provider cancellation 与当前 CANCELLED。DETECTED_ONLY 失败记录 SUBSCRIPTION_NOT_MANAGED，自动测试确认没有 Approval、Operation 或 Provider write。

## 12. Prompt Injection Defense

攻击者可以影响 LLM 自由文本，但不能替换 server Principal、Tool allowlist、注册策略、Workflow state machine 或 Action API 安全 gate。新增攻击测试覆盖管理员声明、跳过 Approval、跳过 RED reauth、直接 write Tool、Principal switch、跨用户 UUID、Planner authority 字段和 Tool output injection。

Tool output injection 的 display_name 确实进入模型上下文；测试让 Fake LLM 读取注入后主动请求 write Tool，runtime 仍拒绝。该测试证明执行边界，不证明模型永远不会受文本影响。

## 13. Hallucination Defense

执行成功是强确定性保证：Workflow 与 Operation 同为 SUCCEEDED 才生成产品成功；UNKNOWN、SUBMITTED、Task COMPLETED、Approval/reauth 通过均不是业务成功。金融核心事实来自 typed backend result，错误 balance prose 不改变 card；Condition prose 不改变 FALSE。

解释文本是 bounded mitigation：报告 schema/evidence/numeric validator 保留，不声称逐句 semantic entailment。LLM 仍可能生成不恰当解释；本轮固定报告重复10次通过，只证明该测试窗口。没有第二个 LLM verifier 或通用 prose 数字解析器。

## 14. Least Privilege / Default Deny

minimal agent 仅 account.list/account.get_balance；financial agent 仅既有账户/消费/异常读工具；subscription agent 仅 subscription.analyze。monthly report Skill allowed_tools=[]。只有注册 workflow:transfer / transfer.commit、workflow:subscription-cancel / subscription.cancel 配对拥有受约束 write authority。未知 Tool、调用者、allowlist、risk/side-effect 不匹配均 DENY。Recovery 使用原 Operation 与既有 Workflow 边界，不拥有通用任意 Tool caller。

## 15. Idempotency / Concurrency

保留 provider idempotency key、Operation unique Workflow/type 与 Approval consumption 约束、Mock provider account advisory lock、user risk lock、security user lock、Task claim/lease/fencing 和 transactional Outbox。Audit 只在 owner-scoped Operation 当前详情提供完整幂等身份，既有 SSE Event 仍不包含该 key。新增记录不释放新 Operation 创建中的安全/risk 锁；Provider I/O 在 snapshot transaction 结束后进行，recovery 仍被 lease owner fence。

## 16. Authentication / Ownership

OIDC-ready：signature/iss/aud/exp/nbf/sub/kid/JWKS/algorithm 由 server 验证。development Principal 仅 dev/test；production 禁止 development auth。查询/Actions/Audit 均校验 owner；知道 UUID 不获得 authority。生产 IdP 接入及真实银行 integration：NOT IMPLEMENTED。

## 17. Code Execution / Sandbox Boundary

当前产品不提供 LLM 生成并执行任意 Python/Shell/SQL 的能力。因此 Agent 调用链不存在模型任意代码执行路径。后端执行开发者预定义代码与注册 Tool。开发者 CLI/Test harness 不是模型可调用 Capability。未来若加入 Code Tool，必须进入受限 Sandbox；本轮未添加 Code Executor。

## 18. Threat Model

| Trust boundary | Asset / Threat | Control | Residual risk | Evidence |
|---|---|---|---|---|
| User → Browser | 请求意图 / 伪造确认、UUID | 显式 Domain Actions、server owner | 用户可误确认合法草稿 | Action bypass / mutation tests |
| Browser → API | 金额与授权 / 修改请求、版本重放 | Decimal/schema、expected_version、canonical hash | 被盗会话可作该用户授权 | expiry/mutation/stale/ownership tests |
| LLM Provider → Agent Runtime | 路由/输出 / injection、虚构成功 | server Principal、注册 allowlist、typed outputs | 解释误导、服务失败 | adversarial + wrong prose tests |
| Agent Runtime → Tool Executor | capability / 未知/写 Tool | Default Deny caller/allowlist/risk | 已注册 Tool 本身的代码缺陷 | least privilege matrix |
| Tool Executor → Application Service | write payload / 绕过流程 | Workflow、Approval、reauth、Guard | 应用开发错误 | direct Actions regressions |
| Application Service → PostgreSQL | 状态、审计 / race、重复、owner 泄漏 | transaction/constraint/locks/lease/fencing | privileged DB 篡改、reset 删除 | postgres concurrency/outbox/audit |
| Application Service → Mock Provider | 余额、ledger / 超支、重提交、unknown | account lock、持久 idempotency、reconcile | 非真实银行、故障语义有限 | provider concurrency/recovery |
| OIDC boundary → Principal | 身份 / 假 token、跨用户 | JWT/JWKS/asymmetric validation、stable mapping | IdP/credential compromise | authentication/isolation tests |
| SSE / Outbox → Browser | 通知 / 丢失、重复、错序 | transaction Outbox、序号、刷新 authoritative resources | process-local EventBus；重复通知 | Outbox/SSE regressions |

## 19. Security Self-Assessment

| Permission | 规则与确定性控制 | 实现位置 | 测试证据 | 限制 |
|---|---|---|---|---|
| GREEN | 已授权用户 read-only Tool；Guard 写锁不阻断查询 | PolicyService / ToolExecutor / domain ownership | read tools、least privilege、WRITE_LOCKED read | synthetic data、解释文本不做 entailment |
| YELLOW | CNY exposure <=1000 或 managed subscription cancellation；必须 Approval | TransferRiskPolicy、WorkflowService、OperationService | boundary、Approval mutation/expiry、direct commit deny | fixed CNY competition rule |
| RED | CNY projected exposure >1000；Approval + fresh reauth | commit-time risk reevaluation + reauth binding/TTL | 600 exposure RED、escalation、RED no reauth deny | Mock MFA，非真实身份强保证 |

安全边界依赖 deterministic server code、typed state、DB constraints 和 Provider boundary，不依赖 Prompt、fixture 偶然性或浏览器。详细真实证据与 Manual 状态见 test-results-v0.9.2；未执行项不能成为答辩 PASS 证据。

## 20. Demo Hardening

复用 scoped reset，新增只读 preflight、真实 HTTP audit/security smoke、report stability 计数脚本。用户实际审批必要 synthetic 查询/汇总到当前配置 https://api.deepseek.com 后，隔离测试库的 report、plan、audit、security smoke 全部通过。浏览器最终金融提交由用户亲自完成，未用 API 代替被要求接管的动作。最终停止 worker、scoped reset、Docker build/start、16项 preflight 全部通过。

## 21. Currency Canonicalization

在共同 TransferIntentExtractor 边界，严格将用户原文出现的 CNY/RMB/人民币/元/¥/￥ canonicalize 为 CNY。缺省沿用选中账户币种；未知/矛盾表达要求澄清，不盲目变 CNY。USD/EUR/其他已识别外币仍流入原 deterministic validation / CNY-only policy 拒绝，不实现 FX。直接 Workflow 与实际 Plan extractor 路径均有 alias 回归。

## 22. Report Stability

现有 narrative validator 未削弱，未采用未经验证输出或 fallback。新增 smoke_report_stability.py 默认 10 次串行完整 report product（多个真实 LLM 调用，选择最低允许次数控制耗时/费用），逐次持久 core 对 Golden，全量统计 successes/validation failures/golden mismatch/other failure，任何失败返回非零。计数器及 production 拒绝有自动测试；运行 guard 同时要求隔离库名包含 test。真实运行10次：10 successes、0 narrative validation failures、0 golden mismatches、0 other failures；每次 golden_core_equal=true，exit0。独立 report product 再执行1次也通过。不宣称已永远消除随机失败。

## 23. Demo Preflight

GET /api/v1/demo/readiness 是 owner-scoped、dev/test-only 的只读状态 projection，production 返回 404，不是 reset API，不注册为 Tool。检查运行实例版本、migration、预期账户/余额、exposure、subscriptions、guard、未收敛 Operations、Mock provider/reauth、LLM configured boolean、timezone。CLI 只接受无凭证 localhost HTTP，直接连接本地而不走系统 proxy，输出 PASS/FAIL，不打印密钥/OTP/异常 credential text。真实 reset 后 preflight 已通过。

只读分析 reference clock 可通过 dev/test DEMO_REFERENCE_TIME 注入，默认 real clock。仅 anomaly/renewal projection 使用；production 拒绝。risk business date、Approval/reauth TTL、Guard、Task lease、Operation recovery 均保持真实时间。

## 24. Backend Changes

新增 audit models/safety/projection、task Audit GET、demo readiness GET、strict currency normalization、read-only reference clock。现有 Workflow/Operation/Guard 补记有限安全事实；不修改写业务 authorization 语义或历史 migration。

## 25. Frontend Changes

Conversation Task 增加“查看审计链”；AuditTimeline 按后端顺序展示历史/技术证据/当前资源/zero-write facts，复用 RiskDetails/ConditionCard/status mapping。Mock 标签明确；不存在 prose 解析、前端风险/金额/Condition 重算或成功状态猜测。404 时清除旧 trace 并显示不可用。没有 UI 大改版。

## 26. API/OpenAPI Changes

新增 GET /api/v1/tasks/{task_id}/audit 与 GET /api/v1/demo/readiness；AuditTrace/Entry/Fact/Resource/WriteEvidence/Actor、DemoReadiness DTO。现有写 API 不新增权限。generated schema.d.ts 已由实际 FastAPI OpenAPI 生成；无手写重复 API TS model。

## 27. Migration

Migration added：no。Alembic head：0017。现有 Event/Outbox 存储足够；升级 head 和 PostgreSQL 0015→0016→0017 migration 回归实际执行。

## 28. Security Invariants

CNY-only；Decimal/string money；Default Deny/Least Privilege；server Principal；owner 404；canonical hash/TTL；RED reauth；Guard 新写 gate；Provider ledger/idempotency；lease/fencing；Condition FALSE zero write；UNKNOWN != success；Task COMPLETED != business success；dual Workflow + Operation success。

## 29. Known Risks

Mock MFA、Mock banking Provider、No FX、process-local EventBus、无 semantic entailment verifier、LLM availability/variability、synthetic fixtures、Dashboard non-atomic cross-service projection。新增风险/限制：应用 append-only 不是 DB 防篡改；旧 Event 证据不补造；1000 Event bounded history 会显式截断；Audit 当前快照和多次查询不是全链 atomic snapshot；deadline/ownership 在动作时仍必须再验证；10次真实报告成功不代表任意输入或未来模型稳定。开发 Docker 发布本机端口，使用者必须保持在受信任的开发环境。

## 30. Release Conclusion

**READY**。Backend 561 passed /36 skipped（PostgreSQL独立37 passed）、Frontend 26 passed、全部 lint/typecheck/build、四项真实产品 smoke、10次报告稳定性、S1–S12实际浏览器验收和最终 reset/preflight 均通过。RED人工提交还实际验证了过期 Approval / Reauthentication 必须重新确认和验证；UNKNOWN 历史未被最终成功覆盖；WRITE_LOCKED期间新commit423、GREEN查询可用、已有Operation reconcile200。三个v0.9.2交付文档与README当前入口已同步。没有未完成的本版本scope项；不表示已接入真实银行、真实MFA或完成数据库防篡改认证，也未自动创建Git tag或推送发布。
