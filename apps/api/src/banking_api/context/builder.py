from banking_api.agents.models import AgentDefinition
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
