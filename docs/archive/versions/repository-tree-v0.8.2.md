# 历史档案：v0.8.2 直接修改文件

> 历史材料，保留原记录日期、版本和结论。旧风险规则、待办事项、测试数量与本地部署状态不代表 v0.10.3；当前说明见 [文档导航](../../README.md)。

```text
README.md
apps/api/
├── pyproject.toml / uv.lock                         # v0.8.2
├── migrations/versions/0017_plan_conditions.py       # 最小扩展 plan_steps
├── src/banking_api/
│   ├── main.py                                    # 版本
│   ├── api/routes/plans.py                         # 补回缺失的既有 Plan API
│   ├── domain/plan.py                              # safe Condition response
│   ├── planning/
│   │   ├── models.py                              # kind union、Spec、Decision
│   │   ├── condition_evaluator.py                 # 三种 typed Snapshot 适配
│   │   ├── constraints.py                         # 条件/ELSE 约束
│   │   ├── planner.py                             # 条件意图、禁止省略 guard
│   │   └── validator.py                           # source/guard/DAG 校验
│   ├── persistence/models.py                      # Condition/guard 字段
│   ├── persistence/repositories/plans.py           # 固定 graph 持久化
│   ├── application/plan_execution_service.py       # fence、分支和确定性回答
│   ├── application/plan_service.py                 # response、事件、回退清 Decision
│   └── routing/request_router.py                  # conditional COMPLEX_PLAN
└── tests/
    ├── test_plan_conditions.py                    # schema、evaluator、执行/授权/fence
    ├── test_plan_conditions_postgres.py           # migration、持久化、并发/恢复
    ├── test_plans.py                              # kind schema 与 conditional router
    ├── test_plan_postgres.py                      # 旧迁移测试恢复至 head
    └── test_postgres_integration.py                # 当前 revision 断言
apps/web/features/plans/PlanCard.tsx                 # backend Decision 展示
packages/api-client/src/schema.d.ts                 # 生成响应类型
scripts/smoke_plan_conditions.py                    # 当前 LLM/HTTP A、B
docs/
├── implementation-report-v0.8.2.md
├── repository-tree-v0.8.2.md
└── test-results-v0.8.2.md
```

没有修改原 Operation、Provider、Recovery、OIDC、异常交易或订阅识别算法；没有新增 Worker、表达式引擎或 v0.9 内容。
