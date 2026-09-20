from dataclasses import dataclass


@dataclass(frozen=True)
class AgentDefinition:
    agent_id: str
    instructions: str
    allowed_capabilities: frozenset[str]


MINIMAL_BANKING_AGENT = AgentDefinition(
    agent_id="agent:minimal-banking",
    instructions="""你是一个只读银行助手。

账户和余额事实必须通过银行工具获取。
不要猜测账户或余额。
只使用提供的工具。
如果无法确定账户，向用户说明或询问。
默认使用中文回复。
不得声称执行任何资金或账户写操作。""",
    allowed_capabilities=frozenset({"account.list", "account.get_balance"}),
)
