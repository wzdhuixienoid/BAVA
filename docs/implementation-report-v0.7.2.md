# Implementation Report v0.7.2

## 1. 确定性识别周期扣费

`SubscriptionDetector` 只消费当前 Principal 的 Application transaction data。候选交易必须是 `POSTED + DEBIT + category != TRANSFER`；为避免 synthetic data 中房租和水电被误归类，还需满足显式 `SUBSCRIPTION` category 或受审核的 fixture alias。按 normalized merchant + currency 分组，至少 2 笔证据；月度间隔 25–35 天，年度间隔 350–380 天。

## 2. 为什么不用 LLM 判断订阅事实

LLM 只负责意图和解释。cadence、金额、涨价、续费日期和可取消性都来自确定性 Python/Provider fact，且 Agent 不接收全量 raw history。

## 3. Merchant normalization

`MERCHANT_ALIASES` 是显式 fixture alias 表；标准化只做大小写、空白/分隔符处理和已知 alias 映射。未知商户保持不同 key，不由 LLM 合并。

## 4. MANAGED / DETECTED_ONLY

`MANAGED` 表示周期扣费能匹配当前 Principal 的 synthetic subscription contract；`DETECTED_ONLY` 只表示交易规律。这一区分防止把“银行看到扣款”误表达为“银行可修改商户合同”。

## 5. DETECTED_ONLY 不能取消

没有 provider contract id 和可取消性事实，Workflow 以 `SUBSCRIPTION_NOT_MANAGED` 终止，不创建 Approval、Operation 或 provider fact。

## 6. Subscription Agent Tool 权限

`agent:subscription-analysis` 仅允许 `subscription.analyze`。输入 schema 不接受 `user_id/subject/principal`，scope 只来自 `ToolExecutionContext.principal.user_id`。Agent 没有 `subscription.cancel`、Approval 或 Operation 写权限。

## 7. Cancellation 必须走 Workflow

取消需要确定性解析、歧义选择、复核、Approval、Operation 和 Provider 终态确认。LLM 只提取 `subscription_query`，内部 id 由 resolver 选择。

## 8. 为什么是 YELLOW

取消会改变未来扣费合同，需要明确用户确认；但不是立即资金转出，本版不需 Reauthentication，也不按金额升级 RED。

## 9. Approval payload binding

canonical payload 只包含 `action=SUBSCRIPTION_CANCEL + subscription_id + user_id`，按稳定 JSON 序列化后 SHA-256。commit 前重新解析合同并校验 hash；目标变化时 Approval 不可消费。

## 10. Operation 复用

现有 `operations` 表增加 `SUBSCRIPTION_CANCEL` type，复用 CREATED/SUBMITTED/UNKNOWN/SUCCEEDED/FAILED、lease、retry、Event/Outbox 和统一 recovery worker。仅在 provider dispatch 点按 operation type 最小分派。

## 11. MockSubscriptionProvider ledger

`mock_subscription_cancellations` 持久化 provider reference、user、subscription、idempotency key、status、error 和时间；fixture 不可变，成功 fact 覆盖有效读模型状态。

## 12. 幂等

provider ledger 对 `idempotency_key` 有 unique constraint。同一 Operation 重放返回同一 provider fact/reference；已取消合同的新 Workflow 在 validation 阶段返回 `ALREADY_CANCELLED`。

## 13. crash recovery

Provider accept 后应用未更新终态时，Operation 保持 UNKNOWN。`OperationRecoveryWorker` claim 原 Operation，使用原 idempotency key 查询 provider fact，收敛为 SUCCEEDED，不创建新 Operation。

## 14. read model 取消状态

Subscription API 合并 immutable contract fixture 与持久化 successful cancellation fact。取消后返回 `CANCELLED`，原 transaction fixture 不删除。

## 15. 多币种

月度与预计年度成本使用 `Decimal`，按 currency 分组。不换汇，不输出跨币种总额。

## 16. 幻觉防护

Snapshot 不含 `unused/last_used` 等 usage signal。银行交易只能说明持续扣费、金额变动和预计续费，不能证明用户是否使用服务。

## 17. v0.7.1 两个边界

非 CNY Transfer 已由现有付款账户币种 validation fail closed，保留原有 `CURRENCY_MISMATCH`，三组 regression 证明其不会进入 CNY threshold。跨日 exposure 原先确实会从 Operation creation day 漂移到 provider completion day，因此增加最小 `risk_business_date`，成功与执行中事实统一按该日归属。

## 18. 测试

新增 detector、snapshot、Principal/API 隔离、Tool 权限、YELLOW/no-reauth、detected-only、ambiguity、payload/Approval、success/read-model、idempotency、repeat request、timeout recovery、prompt injection、非 CNY 与跨日 exposure 回归。最终命令和结果见 `test-results-v0.7.2.md`。

## 19. 当前限制

仅固定 monthly/annual cadence window；无 FX；无真实商户 API；无 usage telemetry；无主动续费通知；“重复”只基于同 normalized merchant 的多个 active contract。

## 20. 下一步 v0.7.3

在不改变当前安全边界的前提下，可扩展更细的 cadence/金额容差配置、更多 synthetic provider contract 状态，以及经用户明确授权的续费通知能力。
