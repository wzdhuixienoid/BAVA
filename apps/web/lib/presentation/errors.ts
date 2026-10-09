const errorLabels: Record<string, string> = {
  CONVERSATION_HAS_ACTIVE_TASKS: "该对话还有未结束的任务，请先完成或取消相关流程。",
  SUBSCRIPTION_REVIEW_CHANGED: "订阅资料已更新，请重新核对后确认。",
  SUBSCRIPTION_VERSION_CONFLICT: "订阅状态已变化，请刷新后重新发起操作。",
  SUBSCRIPTION_NOT_RESUMABLE: "该订阅暂不支持恢复，请到商户办理。",
  PAYEE_CONFIRMATION_REQUIRED: "请核对收款人资料并确认保存。",
  PAYEE_NOT_FOUND: "收款人已不存在，请刷新列表。",
  PAYEE_ALREADY_EXISTS: "相同收款资料已存在，请核对后再保存。",
  PAYEE_HAS_ACTIVE_TRANSFER: "该收款人有未完成的转账，请先完成或取消转账后再编辑或删除。",
  REAUTH_FAILED: "身份验证未通过，请检查模拟验证码；连续失败会暂时锁定写操作。",
  REAUTH_EXPIRED: "身份验证已过期，请重新验证。",
  TRANSFER_RISK_REAUTH_REQUIRED: "这笔转账需要强验证，请完成验证后再提交。",
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
