"use client";
import { queryTime } from "@/lib/presentation/time";

import { useEffect, useState } from "react";
import type { components } from "@banking/api-client";
import { statusDisplay } from "@/lib/presentation/status";
import { api } from "@/lib/api/client";

type Event = components["schemas"]["Event"];

const labels: Record<string, string> = {
  "wealth.order.accepted": "模拟理财已受理，资金或份额占用中",
  "wealth.order.confirmed": "模拟理财已成交，等待最终结算",
  "wealth.order.settled": "模拟理财最终完成",
  "wealth.order.rejected": "模拟理财明确拒绝，未占用资金",
  "wealth.order.failed": "模拟理财明确失败",

  "task.created": "已收到你的请求",
  "task.started": "开始理解你的需求",
  "task.completed": "结果已整理完成",
  "task.failed": "处理未完成",
  "task.interrupted": "处理中断，等待恢复",
  "task.rescheduled": "已安排继续处理",
  "llm.request.started": "正在分析需求与已有信息",
  "llm.request.completed": "已确定下一步处理方式",
  "skill.run.started": "正在生成消费报告",
  "skill.run.completed": "消费报告内容已准备完成",
  "skill.run.failed": "报告生成未完成",
  "report.generated": "消费报告已生成",
  "workflow.created": "业务草稿已建立",
  "workflow.waiting_for_input": "等待补充业务信息",
  "workflow.ready_for_review": "等待核对并确认",
  "workflow.reauth_required": "等待身份验证",
  "workflow.ready_for_commit": "等待提交执行",
  "workflow.committing": "已提交，等待银行结果",
  "workflow.succeeded": "业务流程处理完成",
  "workflow.failed": "业务流程失败",
  "workflow.cancelled": "业务流程已取消",
  "operation.unknown": "执行结果待确认",
  "operation.succeeded": "银行已确认执行成功",
  "operation.failed": "银行确认执行失败",
};

const toolLabels: Record<string, string> = {
  list_accounts: "账户列表", get_balance: "账户余额", get_spending_summary: "收支汇总",
  get_category_breakdown: "消费分类", compare_spending_periods: "不同月份的消费",
  get_top_transactions: "主要交易", detect_transaction_anomalies: "异常交易",
  search_payees: "收款人", get_transfer_status: "转账结果",
  wealth_list_products: "模拟产品目录", wealth_get_product: "模拟产品资料",
  wealth_compare_products: "理财产品对比", wealth_recommend: "适当性匹配与推荐",
  wealth_search_knowledge: "说明书检索", wealth_list_positions: "本人理财持仓",
  wealth_get_orders: "本人理财订单", wealth_purchase_submit: "理财申购提交",
  wealth_redeem_submit: "理财赎回提交", wealth_purchase_status: "申购状态查询",
  wealth_redeem_status: "赎回状态查询",
  analyze_subscriptions: "订阅与周期扣费", get_subscription_cancellation_status: "订阅取消结果",
};

function description(event: Event): string | undefined {
  if (event.data.skill_id === "skill:transaction-anomaly-analysis") {
    if (event.event_type === "skill.run.started") return "正在整理异常交易分析";
    if (event.event_type === "skill.run.completed") return "异常交易分析已整理完成";
  }
  if (event.event_type.startsWith("tool.call.")) {
    const toolName = typeof event.data.tool_name === "string" ? event.data.tool_name : "";
    const action = toolName === "commit_transfer" ? "转账" : toolName === "cancel_subscription" ? "订阅取消" : undefined;
    if (action) {
      if (event.event_type === "tool.call.started") return `正在提交${action}请求`;
      if (event.event_type === "tool.call.completed") return `${action}请求已处理，执行结果以回执为准`;
      if (event.event_type === "tool.call.failed") return `${action}请求处理未完成`;
    }
    const target = toolLabels[toolName] ?? "业务信息";
    if (event.event_type === "tool.call.started") return `正在查询${target}`;
    if (event.event_type === "tool.call.completed") return `${target}已获取`;
    if (event.event_type === "tool.call.failed") return `${target}查询未完成`;
  }
  if (event.event_type === "task.progress" && typeof event.data.message === "string") return event.data.message;
  if (event.event_type === "plan.state_changed" && typeof event.data.to_status === "string") {
    const status = statusDisplay(event.data.to_status).label;
    return status ? `计划${status}` : undefined;
  }
  return labels[event.event_type];
}

export function useTaskActivity(taskIds: string[], revision: string, enabled: boolean) {
  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const ids = taskIds.join(",");

  useEffect(() => {
    if (!enabled || !ids) return;
    let active = true;
    Promise.all(ids.split(",").map((id) => api.listTaskEvents(id))).then((batches) => {
      if (!active) return;
      setEvents([...new Map(batches.flat().map((event) => [event.event_id, event])).values()]);
      setError(null);
    }).catch(() => {
      if (active) setError("暂时无法加载处理过程，请重新展开重试。");
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [ids, revision, enabled]);

  const entries = [...events].sort((a, b) => a.sequence - b.sequence)
    .flatMap((event) => {
      const text = description(event);
      return text ? [{ event, text }] : [];
    }).filter((entry, index, list) => entry.text !== list[index - 1]?.text);
  return { entries, loading, error };
}

export function TaskActivity({ entries, loading, error }: ReturnType<typeof useTaskActivity>) {
  return (
    <div aria-label="处理过程" className="text-xs leading-relaxed text-slate-500">
      {loading && entries.length === 0 && <p>正在读取处理过程…</p>}
      {error && <p className="text-amber-700">{error}</p>}
      {!loading && !error && entries.length === 0 && <p>暂无过程记录。</p>}
      <ol className="space-y-2 border-l-2 border-slate-200 pl-4">
        {entries.map(({ event, text }) => <li key={event.event_id} title={queryTime(event.timestamp)}>
          {text}
        </li>)}
      </ol>
    </div>
  );
}
