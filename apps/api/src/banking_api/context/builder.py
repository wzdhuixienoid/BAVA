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
                        "未指定期间的消费统计及近期/最近消费按最近完整自然月 "
                        f"{previous_month} 分析，"
                        "明确说明该默认范围；异常识别仍按工具的近30天窗口，不能混用期间。"
                        "必须在回答说明所用期间，不能猜测其他年份或把历史对话的期间用于新请求。"
                        "年度查询使用 YYYY，月度查询使用 YYYY-MM。"
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
