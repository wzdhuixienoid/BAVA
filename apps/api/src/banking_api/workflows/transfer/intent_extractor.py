import json

from pydantic import ValidationError

from banking_api.llm.models import LLMMessage, LLMRequest
from banking_api.llm.provider import LLMProvider, LLMProviderError
from banking_api.workflows.transfer.currency import canonicalize_currency
from banking_api.workflows.transfer.models import TransferIntent

EXTRACTION_INSTRUCTIONS = """
你是转账意图结构化提取器。只输出一个 JSON 对象，且只允许四个字段：
{"recipient_query":string|null,"amount":string|null,"currency":string|null,"source_account_hint":string|null}

只提取用户表达的语义值。禁止输出 payee_id、account_id、workflow_id 或任何内部 ID。
金额必须使用十进制字符串；未说明的字段使用 null。不要猜测。
currency 使用明确表达的 ISO 币种代码：人民币/元对应 CNY，美元对应 USD，欧元对应 EUR；
没有表达币种时使用 null，不输出“元”等单位，不进行换汇。
复合条件请求中 amount 只提取转账动作的金额，余额条件阈值不是转账金额。
不要输出解释、Markdown 或推理过程。
""".strip()


class TransferIntentExtractionError(Exception):
    pass


class TransferIntentExtractor:
    def __init__(self, provider: LLMProvider, *, max_retries: int = 1) -> None:
        self._provider = provider
        self._max_retries = max_retries

    async def extract(self, user_request: str) -> TransferIntent:
        messages = [
            LLMMessage(role="system", content=EXTRACTION_INSTRUCTIONS),
            LLMMessage(role="user", content=user_request),
        ]
        for attempt in range(self._max_retries + 1):
            request = LLMRequest(messages=messages)
            try:
                response = await self._provider.generate(request)
                if response.tool_calls or not response.content:
                    raise ValueError("non-structured response")
                payload = self._parse_json(response.content)
                intent = TransferIntent.model_validate(payload)
                intent.currency = canonicalize_currency(intent.currency, user_request)
                return intent
            except (json.JSONDecodeError, ValidationError, TypeError, ValueError, LLMProviderError):
                if attempt < self._max_retries:
                    messages = [
                        *messages,
                        LLMMessage(
                            role="system",
                            content="上一个输出格式无效。请仅按指定 schema 重新输出 JSON。",
                        ),
                    ]
        raise TransferIntentExtractionError("Transfer intent extraction failed")

    @staticmethod
    def _parse_json(content: str) -> object:
        candidate = content.strip()
        if candidate.startswith("```json") and candidate.endswith("```"):
            candidate = candidate[7:-3].strip()
        elif candidate.startswith("```") and candidate.endswith("```"):
            candidate = candidate[3:-3].strip()
        return json.loads(candidate)
