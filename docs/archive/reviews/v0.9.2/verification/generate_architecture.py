"""Generate a local vector architecture figure; not a product/Agent code tool."""

from html import escape
from pathlib import Path

DESTINATION = Path(__file__).resolve().parents[1] / "assets" / "system-architecture.svg"

parts = [
    '<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="1560" viewBox="0 0 1440 1560">',
    '<title>AI Banking Agent v0.9.2 当前系统架构</title>',
    '<desc>模块化单体、受限模型路径、确定性写入边界、持久化和三个专用后台loop。</desc>',
    '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10Z" fill="#64748b"/></marker></defs>',
    '<rect width="1440" height="1560" fill="#f8fafc"/>',
    '<style>text{font-family:"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif;fill:#0f172a}.title{font-size:32px;font-weight:700}.sub{font-size:18px;fill:#64748b}.head{font-size:22px;font-weight:700}.line{font-size:17px}.label{font-size:16px;fill:#475569}.edge{fill:none;stroke:#64748b;stroke-width:2.5;marker-end:url(#arrow)}</style>',
    '<text class="title" x="50" y="52">AI Banking Agent · v0.9.2</text>',
    '<text class="sub" x="50" y="84">当前实现 · 2026-10-05 · Web + FastAPI 模块化单体 + PostgreSQL</text>',
]


def box(x, y, w, h, heading, lines, color="#e0f2fe", stroke="#7dd3fc"):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{color}" stroke="{stroke}" stroke-width="1.5"/>')
    parts.append(f'<text class="head" x="{x+20}" y="{y+34}">{escape(heading)}</text>')
    for index, line in enumerate(lines):
        parts.append(f'<text class="line" x="{x+20}" y="{y+62+24*index}">{escape(line)}</text>')


def edge(points, label=None, label_x=0, label_y=0, dashed=False):
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    parts.append(f'<path class="edge" d="{points}"{dash}/>')
    if label:
        parts.append(f'<text class="label" x="{label_x}" y="{label_y}">{escape(label)}</text>')


box(40, 120, 430, 112, "用户 / Next.js Web", ["中文文本、候选选择、明确确认", "工作台 / Dashboard / Reports / 订阅"])
box(510, 120, 430, 112, "FastAPI Domain API", ["服务器 Principal / ownership / typed DTO", "HTTP、fetch SSE；OIDC-ready 或开发身份"])
box(980, 120, 420, 112, "LLM Provider（受约束）", ["Router / 意图提取 / Planner / 查询解释", "只读 Tool 选择与受校验报告说明"], "#ede9fe", "#c4b5fd")
edge("M470 176 H510", "HTTP", 476, 162)
edge("M940 176 H980", dashed=True)

box(40, 280, 1360, 110, "持久消息与 Task 执行", ["Message + Task + Event + Outbox 原子提交 → PostgreSQL Task claim / lease / heartbeat / attempt fence", "TaskExecutionWorker → InProcessTaskRunner → RequestRouter（分类不授予权限）"], "#dbeafe", "#93c5fd")
edge("M725 232 V280")

box(40, 450, 420, 124, "简单只读 Agent", ["Minimal / Financial / Subscription", "共用 LangGraph：LLM ↔ Tool", "最多 6 LLM steps / 4 Tool calls"], "#ede9fe", "#c4b5fd")
box(510, 450, 420, 124, "受约束 Plan DAG", ["Planner → Validator → Persistent DAG", "最多 8 步 / 2 条件 / 1 写 Workflow", "复用同一 Task Worker / 原有能力"], "#ede9fe", "#c4b5fd")
box(980, 450, 420, 124, "确定性 Workflow", ["Transfer / SubscriptionCancel", "简单写请求走原路径", "LLM 意图提取后退出资金执行路径"], "#fef3c7", "#fcd34d")
edge("M250 390 V450")
edge("M720 390 V450")
edge("M1190 390 V450")

box(40, 635, 420, 136, "只读 Tool / Domain 服务", ["Registry → Policy → Executor", "Decimal Analytics / Subscription / Anomaly", "typed bounded facts；用户范围内读取", "FinancialSnapshot → Report Skill"], "#ccfbf1", "#5eead4")
box(510, 635, 420, 136, "确定性 CONDITION", ["已完成 source → typed facts + Decimal", "原文 threshold / Decision + source hash", "FALSE → SKIPPED，零业务写资源", "TRUE → 原 Workflow，仍需用户控制"], "#ccfbf1", "#5eead4")
box(980, 635, 420, 136, "写入前安全边界", ["RiskDecision / Approval hash + TTL", "RED Mock Reauthentication / SecurityGuard", "Guard 用户锁 → Transfer Risk 用户锁", "commit-time exposure 与授权重校验"], "#fef3c7", "#fcd34d")
edge("M250 574 V635")
edge("M720 574 V635")
edge("M1190 574 V635")
edge("M930 705 H980", "TRUE", 935, 692)
edge("M510 550 H460", "读能力", 465, 535)

box(40, 830, 420, 112, "报告与只读 Projection", ["Python report core + 受校验 LLM prose", "immutable Report / Dashboard / Audit", "后端决定事实，前端直接展示"], "#ccfbf1", "#5eead4")
box(510, 830, 420, 112, "OperationService", ["Operation + Approval CONSUMED", "Workflow COMMITTING + Event/Outbox", "同事务提交，随后 Provider I/O"], "#fef3c7", "#fcd34d")
box(980, 830, 420, 112, "Mock Banking Providers", ["Transfer / Subscription cancellation", "固定 idempotency key + 持久 ledger", "账户锁内重查余额与原子提交"], "#fef3c7", "#fcd34d")
edge("M250 771 V830")
edge("M1190 771 V800 H720 V830")
edge("M930 886 H980", "写 Tool", 934, 871)

box(40, 1000, 870, 124, "Application PostgreSQL · Alembic head 0017", ["Conversation / Message / Task / Event / Outbox / Report", "Workflow / Approval / Reauth / Operation / Guard / Identity / Plan DAG / Provider ledger", "业务与调度事实源；业务成功须 Workflow + Operation 均为 SUCCEEDED"], "#dbeafe", "#93c5fd")
box(950, 1000, 450, 145, "Runtime checkpoint / fixture", ["LangGraph PostgreSQL checkpoint tables", "committed JSON：4账户 / 140交易", "6收款人 / 5订阅合同 / Golden", "checkpoint 不替代银行业务状态"], "#dbeafe", "#93c5fd")
edge("M250 942 V1000")
edge("M720 942 V1000")
edge("M1190 942 V967 H880 V1000")

box(40, 1180, 420, 136, "TaskExecutionWorker", ["due / SKIP LOCKED / lease / heartbeat", "attempt fencing / 退避 / 崩溃接管", "Plan 不另建 Worker", "API 进程托管专用 loop"], "#e2e8f0", "#cbd5e1")
box(510, 1180, 420, 136, "OperationRecoveryWorker", ["只处理已有 CREATED/SUBMITTED/UNKNOWN", "CREATED 用原 key；UNKNOWN 只查询", "不新授权、不换 key 重提", "复用 OperationService / Provider"], "#e2e8f0", "#cbd5e1")
box(980, 1180, 420, 136, "OutboxPublisher → SSE", ["lease / 至少一次发布 / 同 event 可重发", "进程内 EventBus，无跨进程 broker", "SSE 提示浏览器重新 GET 资源", "不等于客户端已收到或业务成功"], "#e2e8f0", "#cbd5e1")
edge("M250 1124 V1180")
edge("M720 1124 V1180")
edge("M900 1090 H930 V1150 H1190 V1180")

parts.extend([
    '<text class="head" x="50" y="1380">图示边界</text>',
    '<text class="line" x="50" y="1415">紫：受约束模型路径　绿：确定性查询/条件/事实　黄：确认与写业务　蓝：持久化　灰：专用后台 loop</text>',
    '<text class="line" x="50" y="1448">当前：合成银行数据、Mock Provider / Mock 强验证、单 API Demo；OIDC 认证边界已实现但未接生产 IdP。</text>',
    '<text class="line" x="50" y="1481">尚无：理财 / 卡片管理 / 定时支付 / AA / 生日下单 / 真实银行与 MFA / 任意模型代码执行沙箱。</text>',
    '<text class="sub" x="50" y="1520">注：新发现原文条件和币种校验缺口、非 ASCII 验证码异常，见 docs/archive/reviews/v0.9.2/requirements-and-findings.md。</text>',
    '</svg>',
])
DESTINATION.parent.mkdir(parents=True, exist_ok=True)
DESTINATION.write_text("\n".join(parts) + "\n", encoding="utf-8")
print(DESTINATION)
