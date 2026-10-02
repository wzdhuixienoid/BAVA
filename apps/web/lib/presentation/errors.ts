const errorLabels: Record<string, string> = {
  REAUTH_FAILED: "身份验证未通过，请检查模拟验证码；连续失败会暂时锁定写操作。",
  REAUTH_EXPIRED: "身份验证已过期，请重新验证。",
  REAUTH_REQUIRED: "当前风险要求完成身份验证后再提交。",
  APPROVAL_EXPIRED: "本次确认已过期，请重新核对并确认。",
  APPROVAL_REQUIRED: "请先核对业务内容并确认。",
  WRITE_LOCKED: "写操作已临时锁定，查询与已有操作结果确认仍可使用。",
  SECURITY_WRITE_LOCKED: "写操作已临时锁定，查询与已有操作结果确认仍可使用。",
  CURRENCY_MISMATCH: "转账币种与付款账户币种不一致。",
  TRANSFER_RISK_CURRENCY_UNSUPPORTED: "比赛转账风险策略仅支持 CNY，当前币种不受支持。",
  INSUFFICIENT_FUNDS: "付款账户可用余额不足。",
  WORKFLOW_VERSION_CONFLICT: "业务状态已更新，请刷新后继续操作。",
  OPERATION_VERSION_CONFLICT: "银行操作状态已更新，请刷新后继续操作。",
  PLAN_ROLLBACK_NOT_SAFE: "该范围包含写流程，不能安全回退。",
};

// Presentation only: the server still decides whether any action is allowed.
export function errorDisplay(code: string): string {
  return errorLabels[code] ?? code;
}
