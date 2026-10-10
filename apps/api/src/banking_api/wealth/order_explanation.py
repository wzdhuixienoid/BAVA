"""User-facing order facts, never a reason to resubmit an unknown operation."""

from banking_api.wealth.calculation import utc

ERRORS = {
    "INSUFFICIENT_FUNDS": ("账户可用余额不足，订单未受理", "核对账户可用余额后重新确认交易"),
    "INSUFFICIENT_SHARES": ("可赎回份额不足，订单未受理", "刷新持仓并重新核对具体赎回份额"),
    "PRODUCT_NOT_TRADABLE": ("产品当前不可交易", "查看当前产品状态，选择符合条件的产品"),
    "PRODUCT_DOCUMENT_CONFLICT": ("产品资料异常，已停止新申购", "等待产品资料修复后重新核对"),
    "AUTHORIZATION_EXPIRED": (
        "产品、日期、测评或确认／强验证授权已失效",
        "重新核对、确认并完成强验证",
    ),
    "WEALTH_DISABLED": ("已暂停新理财交易，订单未受理", "功能恢复后重新核对；已受理订单继续处理"),
    "PROVIDER_REJECTED": ("模拟服务明确拒绝受理", "查看拒绝原因，重新核对交易条件"),
    "NAV_MISSING": ("缺少成交日已发布净值，尚未成交，占用保留", "等待原订单恢复查询，无需重新下单"),
    "SECURITY_WRITE_LOCKED": ("安全保护阻止新的交易受理", "待安全保护解除后重新核对"),
    "PRICING_BOUNDARY": ("计价边界不满足正份额或非负余款要求", "调整数量后重新核对"),
}
STAGES = {
    "CREATED": "待受理",
    "ACCEPTED": "已受理，待成交",
    "CONFIRMED": "已成交，待到账",
    "SETTLED": "最终完成",
    "REJECTED": "未受理",
    "FAILED": "明确失败",
}


def explain_order(order, operation, hold_active):
    unknown = operation is not None and operation.status.value == "UNKNOWN"
    code = order.error_code or (operation.error_code if operation is not None else None)
    reason, next_step = ERRORS.get(code, ("订单正在按约定时间处理", "等待原订单处理并查看进度"))
    if order.status == "SETTLED":
        reason, next_step = "实际成交和资金／份额入账已完成", "可查看实际结果和审计过程"
    elif order.status == "CONFIRMED" and order.direction == "REDEEM":
        reason, next_step = "赎回已成交并扣减份额，资金尚未到账", "等待原订单到账，不要重复赎回"
    elif unknown:
        code = code or "RESULT_UNKNOWN"
        reason, next_step = (
            "结果仍在确认，占用保留，最后已知阶段为" + STAGES[order.status],
            "等待查询原订单，无需重新下单",
        )
    elif order.status in {"REJECTED", "FAILED"}:
        reason += "；无资金或份额占用" if not hold_active else "；占用仍在核实"
    return {
        "error_code": code,
        "user_reason": reason,
        "next_step": next_step,
        "last_known_stage": STAGES[order.status],
        "next_processing_at": (
            utc(operation.next_reconcile_at) if operation.next_reconcile_at else None
        )
        if operation is not None and order.status not in {"SETTLED", "REJECTED", "FAILED"}
        else None,
        "hold_retained": bool(hold_active),
    }
