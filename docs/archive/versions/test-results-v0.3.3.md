# 历史档案：AI Banking Agent — v0.3.3 Test Results

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

执行日期：2026-09-22（Asia/Shanghai）。

## Automated summary

| Gate | Result | Evidence |
|---|---|---|
| v0.3.2 preflight | PASS | `131 passed, 3 skipped` |
| uv lock | PASS | `Resolved 69 packages` |
| Ruff | PASS | API source, tests and scripts: `All checks passed!` |
| Default SQLite/Fake pytest | PASS | `148 passed, 3 skipped in 0.69s` |
| Monthly report focused suite | PASS | `17 passed in 0.04s` |
| PostgreSQL integration | PASS | `3 passed, 148 deselected in 0.33s` |
| Golden report grounding | PASS | complete serialized core exact match |
| Real DeepSeek Skill smoke | PASS | core exact, 5 insights, 0 tools |
| OpenAPI generation | PASS | TypeScript schema generated from running API |
| Frontend lint/typecheck/build | PASS | ESLint, `tsc --noEmit`, Next production build |
| Docker Compose/API health | PASS | API/Web built; API v0.3.3; `{"status":"ok"}` |

## Deterministic core assertions

| Metric | Exact | Display |
|---|---:|---:|
| total_spending | 16547.30 | ¥16,547.30 |
| previous_spending | 9333.20 | ¥9,333.20 |
| absolute_change | 7214.10 | +¥7,214.10 |
| percentage_change | 77.29503278618265975228217546 | +77.3% |
| FOOD change | 589.10 | +¥589.10 |
| SHOPPING change | 2662.00 | +¥2,662.00 |
| TRAVEL change | 4260.00 | +¥4,260.00 |

## Skill behavior assertions

- Input runtime type 只接受 `FinancialAnalysisSnapshot`。
- Summary/category/tool evidence 缺失在 LLM call 前 fail closed。
- Comparison/top 缺失生成 `PARTIAL` 且提供 deterministic notes。
- Category amount-descending 顺序和 Top N 顺序原样保留。
- LLM requests 的 `tools` 恒为空列表。
- Unknown evidence/category/account 和 narrative numeric leakage 在一次修正后仍无效时 fail closed。
- Malformed JSON 可修正一次。
- Unexpected Tool Call 立即失败，不交给模型修正。
- Provider failure 映射为 structured Skill error。

## Real DeepSeek smoke

Sanitized configuration：

```text
provider=openai_compatible
base_url_domain=api.deepseek.com
model=deepseek-v4-flash
```

```text
skill=skill:monthly-spending-report
period=2026-08
golden_core_equal=true
headline_exists=true
insight_count=5
all_evidence_refs_valid=true
narrative_numeric_leakage=false
tool_calls=0
data_quality=COMPLETE
```

Smoke 只输出脱敏 provider config、core summary、headline/insights/evidence refs 和 validation summary，不输出 API Key 或 Chain-of-Thought。
