"""Replaceable deterministic retrieval. Documents are evidence, never authority."""

from typing import Protocol

from banking_api.wealth.schemas import WealthKnowledgeResult

ALIASES = [
    ("申购", "购买"),
    ("赎回", "卖出"),
    ("费用", "手续费", "费率"),
    ("开放日", "开放", "星期"),
    ("风险", "损失", "保本"),
    ("净值", "收益"),
    ("到账", "确认", "成交"),
]


class WealthKnowledgeRetriever(Protocol):
    async def search(
        self, product_id: str, query: str, version_id: str | None = None
    ) -> list[WealthKnowledgeResult]: ...


class KeywordWealthKnowledge:
    def __init__(self, service):
        self.service = service

    async def search(self, product_id, query, version_id=None):
        version = await self.service.version(product_id, version_id)
        docs = await self.service.documents(version, historical=version_id is not None)
        from banking_api.wealth.catalog import digest

        docs = [
            d
            for d in docs
            if d.content_hash == digest(d.content)
            and version.terms.get("document_hashes", {}).get(d.document_id) == d.content_hash
        ]
        words = set(query.split())
        for group in ALIASES:
            if any(w in query for w in group):
                words.update(group)
        scored = [(sum(word in d.content or word in d.section for word in words), d) for d in docs]
        scored.sort(key=lambda item: (-item[0], item[1].document_id))
        return [
            WealthKnowledgeResult(
                document_id=d.document_id,
                version=d.version,
                section=d.section,
                source=d.source,
                content=d.content[:800],
            )
            for score, d in scored[:5]
            if score > 0
        ]
