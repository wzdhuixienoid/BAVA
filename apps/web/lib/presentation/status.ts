import type { components } from "@banking/api-client";

type Status = components["schemas"]["TaskStatus"] | components["schemas"]["WorkflowStatus"]
  | components["schemas"]["OperationStatus"] | components["schemas"]["ApprovalStatus"]
  | components["schemas"]["ReauthenticationStatus"] | components["schemas"]["PlanStatus"]
  | components["schemas"]["PlanStepStatus"] | components["schemas"]["SecurityGuardStatus"]
  | components["schemas"]["SubscriptionStatus"] | components["schemas"]["WorkflowStageStatus"];

export type StatusDisplay = { label: string; description: string; tone: "neutral" | "blue" | "amber" | "green" | "red"; icon: string };
export const statuses = {
  PENDING: { label: "等待处理", description: "等待前置步骤或执行调度", tone: "neutral", icon: "○" },
  RUNNING: { label: "执行中", description: "正在处理当前任务", tone: "blue", icon: "◉" },
  INTERRUPTED: { label: "已中断", description: "等待恢复执行", tone: "amber", icon: "Ⅱ" },
  WAITING_USER: { label: "等待用户操作", description: "请完成当前确认或输入", tone: "amber", icon: "◇" },
  WAITING_EXTERNAL: { label: "等待外部确认", description: "银行处理结果尚未收敛", tone: "blue", icon: "◷" },
  COMPLETED: { label: "已完成", description: "任务步骤已完成，不代表写业务成功", tone: "green", icon: "✓" },
  FAILED: { label: "已失败", description: "处理未完成，请查看具体原因", tone: "red", icon: "!" },
  CANCELLED: { label: "已取消", description: "该流程或订阅已取消", tone: "neutral", icon: "−" },
  SKIPPED: { label: "已跳过", description: "后端决定跳过该步骤", tone: "neutral", icon: "↷" },
  DRAFT: { label: "准备草稿", description: "正在准备业务需求", tone: "neutral", icon: "○" },
  WAITING_FOR_INPUT: { label: "等待补充信息", description: "请明确选择业务对象", tone: "amber", icon: "◇" },
  VALIDATING: { label: "校验中", description: "正在校验业务事实", tone: "blue", icon: "◷" },
  READY_FOR_REVIEW: { label: "等待确认", description: "草稿已校验，尚未批准或提交", tone: "amber", icon: "◇" },
  REAUTH_REQUIRED: { label: "需要身份验证", description: "完成模拟强身份验证后才能继续", tone: "amber", icon: "◇" },
  READY_FOR_COMMIT: { label: "可以提交", description: "安全控制已满足，尚未执行业务", tone: "blue", icon: "→" },
  COMMITTING: { label: "正在提交", description: "等待银行最终处理结果", tone: "blue", icon: "◷" },
  SUCCEEDED: { label: "已成功", description: "对应业务资源已由银行确认", tone: "green", icon: "✓" },
  CREATED: { label: "操作已创建", description: "操作已持久化，等待提交", tone: "blue", icon: "○" },
  SUBMITTED: { label: "银行处理中", description: "已提交，不代表最终成功", tone: "blue", icon: "◷" },
  UNKNOWN: { label: "结果确认中", description: "结果尚不明确，请勿重复提交", tone: "amber", icon: "◷" },
  APPROVED: { label: "用户已确认", description: "确认已绑定当前业务内容", tone: "green", icon: "✓" },
  EXPIRED: { label: "已过期", description: "需要重新完成安全控制", tone: "amber", icon: "◷" },
  INVALIDATED: { label: "已失效", description: "业务内容变更后原确认或验证失效", tone: "amber", icon: "−" },
  CONSUMED: { label: "确认已使用", description: "已绑定唯一业务操作", tone: "green", icon: "✓" },
  VERIFIED: { label: "验证已通过", description: "强验证通过，不代表业务已执行", tone: "green", icon: "✓" },
  PAUSED: { label: "已暂停", description: "当前由用户手动处理，等待继续", tone: "amber", icon: "Ⅱ" },
  NORMAL: { label: "安全状态正常", description: "新写操作仍须满足各自安全控制", tone: "green", icon: "✓" },
  WRITE_LOCKED: { label: "写操作已临时锁定", description: "查询仍可使用，新写操作暂时暂停", tone: "red", icon: "!" },
  ACTIVE: { label: "活跃", description: "订阅处于活跃状态", tone: "green", icon: "◉" },
} satisfies Record<Status, StatusDisplay>;

export const tones = {
  neutral: "bg-slate-100 text-slate-600 border-slate-200", blue: "bg-cyan-50 text-cyan-800 border-cyan-200",
  amber: "bg-amber-50 text-amber-800 border-amber-200", green: "bg-emerald-50 text-emerald-800 border-emerald-200",
  red: "bg-red-50 text-red-800 border-red-200",
};

export function statusDisplay(status: string): StatusDisplay {
  return statuses[status as Status] ?? { label: "状态待同步", description: "请刷新获取最新状态", tone: "neutral", icon: "○" };
}

export const capabilityLabels: Record<components["schemas"]["PlanCapability"], string> = {
  ACCOUNT_QUERY: "账户查询", FINANCIAL_ANALYSIS: "消费分析", SUBSCRIPTION_ANALYSIS: "订阅分析",
  TRANSFER_WORKFLOW: "转账流程", SUBSCRIPTION_RESUME_WORKFLOW: "订阅恢复流程", SUBSCRIPTION_CANCEL_WORKFLOW: "订阅取消流程",
};
export const predicateLabels: Record<components["schemas"]["ConditionPredicate"], string> = {
  ACCOUNT_BALANCE_AT_LEAST: "账户余额不少于", MONTHLY_SPENDING_AT_LEAST: "本月支出不少于",
  SUBSCRIPTION_MONTHLY_COST_AT_LEAST: "每月订阅成本不少于",
};
export function accountTypeLabel(type: string) { return ({ DEBIT: "借记账户", SAVINGS: "储蓄账户", CREDIT: "信用账户" })[type as "DEBIT"] ?? "银行账户"; }
