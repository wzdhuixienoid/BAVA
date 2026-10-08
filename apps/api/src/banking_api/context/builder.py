from datetime import timedelta

from banking_api.agents.models import AgentDefinition
from banking_api.config.demo_time import reference_now
from banking_api.domain.enums import MessageRole
from banking_api.domain.message import Message
from banking_api.llm.models import LLMMessage, LLMRequest, LLMToolDefinition
from banking_api.tools.models import ToolSpec


class ContextBuilder:
    def build(
        self,
        *,
        agent: AgentDefinition,
        current_task: str,
        conversation_messages: list[Message],
        runtime_messages: list[LLMMessage],
        allowed_tools: list[ToolSpec],
    ) -> LLMRequest:
        eligible = [
            message
            for message in conversation_messages
            if message.role in {MessageRole.USER, MessageRole.ASSISTANT}
        ][-10:]
        messages = [LLMMessage(role="system", content=agent.instructions)]
        if agent.agent_id == "agent:financial-analysis":
            now = reference_now()
            previous_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
            messages.append(
                LLMMessage(
                    role="system",
                    content=(
                        f"本次账单分析的业务参考日期是 {now.date().isoformat()}。"
                        f"未指定年份的月份使用 {now.year} 年；本月分析 {now:%Y-%m}。"
                        "未指定期间的近期/最近消费使用 recent_days=30，"
                        "从当前业务时间向前30天到当前业务时间；不要默认改为自然月。"
                        f"用户明确说上月时才分析 {previous_month}。"
                        "异常识别未指定期间时也默认近30天，指定期间时按指定范围分析。"
                        "必须在回答说明所用期间，不能猜测其他年份或把历史对话的期间用于新请求。"
                        "年度查询使用 YYYY，月度查询使用 YYYY-MM。"
                        "用户指定最近N天时使用 recent_days=N，表示参考时间向前N天到参考时间；"
                        "不得改为自然月。"
                        "明确日期区间使用带时区的 start_at 和 end_at，北京时间为 +08:00；"
                        "仅给日期时包含结束日期全天。"
                        "起点包含、终点不包含；日期终点应使用结束日期的次日零点。"
                        "天数或起止日期不清楚时请用户补充；消费工具无法满足需求时说明原因，不能改做异常分析。"
                        "只有用户明确要求异常、可疑或奇怪扣款等检查时才能调用异常工具；普通消费分析禁止调用。"
                        "只询问异常时只调用 detect_transaction_anomalies，不查询消费汇总。"
                        "分类统计优先汇总和分类；仅在用户要求变化或最大消费时补查对应工具。"
                        "无数据时说明该期间没有可分析账单，不反复尝试其他月份，也不能声称生成了报告。"
                    ),
                )
            )
        messages.extend(
            LLMMessage(
                role="user" if message.role is MessageRole.USER else "assistant",
                content=message.content,
            )
            for message in eligible
        )
        current_is_latest = (
            eligible
            and eligible[-1].role is MessageRole.USER
            and eligible[-1].content == current_task
        )
        if not current_is_latest:
            messages.append(LLMMessage(role="user", content=current_task))
        messages.extend(message.model_copy(deep=True) for message in runtime_messages)
        return LLMRequest(
            messages=messages,
            tools=[
                LLMToolDefinition(
                    name=tool.name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                )
                for tool in allowed_tools
            ],
        )
