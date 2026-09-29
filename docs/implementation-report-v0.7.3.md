# Implementation Report v0.7.3

## 1. 四种 anomaly rule

- `AMOUNT_SPIKE`：当前金额至少为过去 90 天同币种消费中位数的 4 倍；4–8 倍为 MEDIUM，至少 8 倍为 HIGH。
- `NEW_MERCHANT_HIGH_AMOUNT`：过去 90 天没有出现的 normalized merchant，且金额至少为中位数的 3 倍；3–6 倍为 MEDIUM，至少 6 倍为 HIGH。
- `RAPID_DUPLICATE`：normalized merchant + currency + exact Decimal amount 在 10 分钟内至少出现两次；2 笔为 MEDIUM，至少 3 笔为 HIGH。
- `SUBSCRIPTION_PRICE_SPIKE`：复用 `SubscriptionDetector` 的确定性 sequence，当期比上期至少上涨 30%；30%–50% 为 MEDIUM，至少 50% 为 HIGH。

## 2. Baseline 构造

Detector 只读当前 Principal 的 `POSTED + DEBIT`。对每个候选交易，baseline 取其之前 90 天、同 Principal、同 currency、`category != TRANSFER` 的交易，不做 FX。`TRANSFER` 可留在历史中，但不进入 merchant baseline。

## 3. 为什么用 median

中位数不会被少量既有大额消费过度拉高，比 average 更适合做用户自身历史的稳健基线。所有金额、中位数、比例和涨幅计算都使用 Python `Decimal`。

## 4. 冷启动 fail conservative

长期 baseline 样本少于 8 笔时，不执行 `AMOUNT_SPIKE` 和 `NEW_MERCHANT_HIGH_AMOUNT`，Snapshot 显式返回 `insufficient_baseline=true`。`RAPID_DUPLICATE` 不依赖长期 baseline，仍可执行。

## 5. 多币种隔离

Baseline 的 key 包含 currency。CNY 只与 CNY 比较，USD 只与 USD 比较，不做汇率换算。

## 6. Anomaly 不等于 fraud

Snapshot 只表达“与历史模式不同、值得关注”。Prompt 和 UI 都不声称已确认诈骗、盗刷或商户恶意；未检出 anomaly 也不证明不存在 fraud。

## 7. Anomaly 不直接触发 lock

历史消费异常可能是合法消费。Detector 是只读分析能力，不冻结账户、不拒绝转账、不取消订阅，也不写 Security Guard state。

## 8. SecurityGuard 状态模型

只有 `NORMAL` 和 `WRITE_LOCKED`。状态存在 `security_guard_states`，包含 lock 期限/原因、reauth 连续失败窗口、bypass 窗口、version 和 updated time。

## 9. 连续 Reauthentication failure

10 分钟窗口内连续失败 3 次触发 15 分钟 `WRITE_LOCKED`。未锁定时成功验证会重置连续失败计数；已锁定时 start/verify 均 fail closed，不存在下一次成功立即解锁。

## 10. Repeated control bypass

用户直接 commit，但 authoritative Workflow 仍在 `READY_FOR_REVIEW` 或 `REAUTH_REQUIRED` 时，记录 `SECURITY_CONTROL_BYPASS_ATTEMPT`。5 分钟内 5 次触发 15 分钟 lock。单次 stale UI 只记一次，不会直接锁定。

## 11. 不计入的普通失败

余额不足、收款人不存在、订阅已取消、Provider timeout / UNKNOWN、金额格式错误、LLM timeout 和数据库临时错误都不调用 Security Guard signal API。

## 12. WRITE_LOCKED 阻止什么

阻止 Transfer Operation 创建、Subscription cancel Operation 创建，以及 RED Workflow 的 reauthentication start/verify。

## 13. 为什么仍允许 GREEN read

熔断是 write protection，不是封禁账户。账户、余额、账单、异常、订阅和 Workflow/Operation 状态查询不会产生金融副作用，因此继续可用。

## 14. 持久化

Alembic `0015` 创建 `security_guard_states`。API process restart 后，新 process 从 PostgreSQL 读取同一 `locked_until`，lock 不会丢失。

## 15. 并发 signal 不丢更新

PostgreSQL 下先获取 Principal-scoped transaction advisory lock，再 `SELECT ... FOR UPDATE`、更新计数、写 Event/Outbox 并提交。新 state 的首次创建也在同一 user lock 内，两个 API process 不会覆盖对方的计数。

### Security Guard 与 Operation 创建的并发线性化

Security signal 状态转移和 Transfer / Subscription cancel 的新 Operation 创建共享 `acquire_security_user_lock(session, user_id)`，使用同一稳定 key 算法的 PostgreSQL transaction-scoped advisory lock。Operation prepare 不通过独立 session 做预检；它在同一 DB transaction 中获取锁、重读/懒清理 Security Guard state、完成授权、创建 Operation，并持锁到 commit。因此只有“signal 先提交则 Operation 拒绝”或“Operation 先提交则随后 lock 阻止新 Operation”两种合法顺序。Transfer 的锁顺序固定为 `Security Guard user lock → Transfer Risk user lock`，没有反向获锁路径；Subscription cancellation 只获取 Security Guard user lock。

## 16. 自动 expiry

没有 worker。每次 status/read/write gate 比较 `locked_until` 与 injected clock；过期后 lazy clear lock 和窗口计数，状态回到 `NORMAL`。

## 17. Operation 创建前 fail closed

`prepare_transfer` 和 `prepare_subscription_cancel` 首先执行 `require_write_allowed(user_id)`。Security Guard 与 Transfer Risk、Approval、Reauthentication、payload hash 和 business validation 是独立且必须全部通过的门。

## 18. Lock 时不消费 Approval

Security Guard check 位于 Approval `FOR UPDATE` 和 `CONSUMED` 转移之前。被 lock 拒绝时，不创建 Operation、不修改 Approval、不调用 Provider。到期后会重新检查 Approval expiry、Risk 和 Reauthentication。

## 19. Event / Outbox

`security.reauth_failed`、`security.control_bypass_attempt` 和 `security.write_lock_activated` 使用现有 `EventPublisher`，与 state 更新在同一 transaction 写入 Event + Outbox。Payload 只包含 user/workflow identity、signal type、attempt count、window、reason 和 lock deadline，不包含验证码、JWT、Prompt 或 Chain-of-Thought。

## 20. 测试结果

最终数据见 [Test Results v0.7.3](test-results-v0.7.3.md)。定向测试覆盖四种 anomaly、冷启动、多币种/Principal 隔离、多标签合并、Prompt Injection、reauth 连续失败/成功重置、bypass、expiry、持久化、Transfer/Subscription fail closed 和 Approval/provider 不变式。

## 21. 当前限制

只分析 synthetic banking facts；无 FX、Fraud ML、完整 Fraud Platform、主动通知、人工审核台、管理员解锁、真实 OTP 或真实银行 Provider。确定性阈值是比赛可解释策略，不是基于真实 fraud labels 的校准模型。

## 22. 下一步 v0.8.1

在保持本版 analytics/enforcement 解耦的前提下，评估更完整的比赛产品体验与可观测性；本版不预先引入 Planner、DAG、跨场景联动或通用规则平台。
