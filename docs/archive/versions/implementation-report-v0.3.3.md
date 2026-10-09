# 历史档案：AI Banking Agent — MonthlySpendingReportSkill v0.3.3

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

Status: `IMPLEMENTED AND VERIFIED`

实施日期：2026-09-22。本轮实现 Snapshot → Skill → Structured Report 的独立路径，未改变 Router 产品行为，未将 Skill 接入 Conversation Task，也未修改 `ManualAgentRuntime`。

## 1. Skill schema

```text
skill_id     = skill:monthly-spending-report
version      = 1
input_schema = FinancialAnalysisSnapshot
output_schema = MonthlySpendingReport
allowed_tools = []
```

`SkillDefinition` 只包含 identity、中文 description、input/output schema 和空 Tool allowlist，没有引入 Plugin Framework。

## 2. SkillRegistry

`SkillRegistry` 仅注册一个 `MonthlySpendingReportSkill.definition`，并拒绝重复 ID。FastAPI application state 暴露 authoritative registry，但 API 和聊天流程不会执行 Skill。

## 3. Skill execution path

```text
FinancialAnalysisSnapshot
    -> validate type/core/tool evidence/scope consistency
    -> MonthlySpendingReportSkill.build_core (Python)
    -> ReportFormatter (Python)
    -> LLMProvider narrative JSON, tools=[]
    -> Pydantic ReportNarrativeDraft
    -> evidence/numeric/category/account validation
    -> MonthlySpendingReport
```

缺少 period、summary、category breakdown 或必要 tool evidence 时在 LLM call 之前返回 `REPORT_INPUT_INCOMPLETE`。任何 LLM Tool Call 立即返回 `SKILL_UNEXPECTED_TOOL_CALL`。Malformed/ungrounded narrative 最多修正一次，仍失败则返回 `REPORT_NARRATIVE_VALIDATION_FAILED`。Provider failure 映射为 `SKILL_LLM_PROVIDER_ERROR`。

## 4. Report schema

`MonthlySpendingReport` 包含：

```text
report_version
period
scope.account_ids
overview
period_comparison?
category_breakdown[]
top_transactions[]
headline
insights[]
data_quality
```

Overview、comparison、category 和 top transaction 同时保留 exact `Decimal` 值与 display-only 字段。Category 和 Top N 严格保留 Snapshot 顺序，不交给 LLM 重排。

## 5. Formatter rules

- Money：两位小数、千分位，CNY 使用 `¥`。
- Change money：正值 `+¥`，负值 `-¥`，零值无符号。
- Percentage change：输入是已计算的百分数，`ROUND_HALF_UP` 到一位小数。
- Ratio/share：Python 将已有 ratio 转换为一位百分比展示。
- Null：`—`。

Formatter 不改动报告中的 underlying Decimal。

## 6. Narrative schema

LLM 只能生成：

```text
headline
insights[2..5]:
  type = STRUCTURE | CHANGE | TRANSACTION | DATA_QUALITY
  title
  narrative
  evidence_refs[]
```

headline/title/narrative 不得包含阿拉伯数字、全角数字、中文数字或常见英文数词。金融数字只存在 Python report core/display fields 中。

## 7. Evidence validation

SkillExecutor 从已生成 report core 构建精确 allowlist，包括 overview、comparison、当前 categories 和 bounded Top N。每条 insight 至少一个 reference，未知 reference 拒绝。未知大写 category token 和未知 `acc_*` account token 同样拒绝。验证不读取 Chain-of-Thought。

## 8. Golden report core

Committed fixture 完整覆盖 2026-08 全账户：

```text
total_spending             = 16547.30     (¥16,547.30)
previous_spending          = 9333.20      (¥9,333.20)
absolute_change            = 7214.10      (+¥7,214.10)
percentage_change_display  = +77.3%
FOOD change                = 589.10
SHOPPING change            = 2662.00
TRAVEL change              = 4260.00
```

Grounding test 对整个 serialized core 做全等比较，不使用 LLM judge。

## 9. Fake test result

Fake Provider 覆盖完整 Snapshot、account-specific Snapshot、Formatter、null percentage、category/Top N 顺序、input incomplete、PARTIAL、unknown evidence/category/account、numeric leakage、malformed JSON retry、unexpected Tool Call 和 provider failure。

## 10. Real DeepSeek smoke

Sanitized configuration：`openai_compatible / api.deepseek.com / deepseek-v4-flash`。

```text
skill_id: skill:monthly-spending-report
core: Golden exact match
headline: present
insights: 5
all evidence refs: valid
tool calls: 0
data quality: COMPLETE
numeric core after narrative merge: unchanged
```

实际 narrative 覆盖消费结构、主要变化和 Top N 证据，未输出 API Key、Chain-of-Thought 或数字。

## 11. Files changed

新增 report models/formatter、SkillDefinition/Registry、MonthlySpendingReportSkill、SkillExecutor、Golden fixture/generator、Fake/grounding tests、real smoke 脚本和四份 v0.3.3 文档。`main.py` 只新增 Skill Registry 注册与版本号，Router/Task/Conversation 行为未改变。

## 12. Known limitations

- Skill 尚未接入 Conversation、Task composite executor、Reports API 或 UI。
- Narrative 的未知 category/account 检测针对 structured reference、大写 category token 和 `acc_*` token；其他自由文本事实仍主要由严格 prompt 与 evidence references 约束。
- Deterministic validator 能证明 evidence ref 存在且文本无数字，但不使用第二个 LLM 判断每句自然语言是否被该 ref 完全 entail。
- 币种符号当前显式支持 CNY/USD/EUR/GBP，其他币种展示 ISO code；不做 FX。

## 13. Deviations

- 为同时满足“缺少核心数据失败”和“缺 comparison/top 可 PARTIAL”，实现将 period、summary、category breakdown 及其 tool evidence 定义为必需核心；comparison 和 top transactions 是可选报告章节。
- Golden generator 是显式一次性命令，测试不调用它。

## 14. Architecture questions

- 03.4 是否需要将 Skill run 表示为独立 executor record，而不是复用 Agent Task executor？
- Reports API 应持久化 exact core + narrative，还是只持久化 Snapshot 并在读取时重建 deterministic core？
- 如果未来允许多语言 narrative，数词检测应扩展为 locale-aware validator，而不应交给 LLM 自证。
