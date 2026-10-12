"""Bounded, replaceable Chinese retrieval. No network at query/startup time."""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from banking_api.wealth.calculation import utc
from banking_api.wealth.catalog import digest
from banking_api.wealth.schemas import WealthEvidence, WealthKnowledgeResult

ALIASES = [
    ("申购", "购买", "买入"),
    ("赎回", "卖出"),
    ("费用", "手续费", "费率", "收费"),
    ("开放日", "开放期", "开放", "星期"),
    ("风险", "损失", "保本", "安全", "亏", "波动"),
    ("净值", "收益", "涨跌"),
    ("到账", "确认", "成交", "什么时候拿到钱", "要等几天", "提现"),
]
OFFICIAL_HOSTS = frozenset(
    {"www.hunan.gov.cn", "dfjrjgj.hunan.gov.cn", "www.boc.cn", "www.bocim.com"}
)


def safe_source(url: str, scope: str) -> bool:
    if scope == "DESIGN":
        return bool(
            re.fullmatch(r"/api/v1/wealth/product-profiles/mock-wealth-\d{2}/mock-design-v\d+", url)
        )
    if scope == "PRODUCT":
        return bool(re.fullmatch(r"/api/v1/wealth/documents/[a-zA-Z0-9:_-]+", url))
    parsed = urlparse(url)
    return (
        parsed.scheme in {"https", "http"}
        and parsed.hostname in OFFICIAL_HOSTS
        and not parsed.username
    )


@lru_cache(maxsize=1)
def education_entries() -> tuple[dict, ...]:
    manifest = json.loads((Path(__file__).parent / "content/wealth_education.json").read_text())
    valid = []
    seen = set()
    for entry in manifest["entries"]:
        if entry["id"] in seen:
            raise ValueError("Duplicate knowledge ID")
        seen.add(entry["id"])
        if not entry.get("enabled"):
            continue
        if entry["content_hash"] != digest(entry["content"]) or not safe_source(
            entry["url"], "EDUCATION"
        ):
            continue  # Invalid content cannot enter the index.
        valid.append(entry)
    return tuple(valid)


def normalized(text):
    return re.sub(r"\s+", "", text.casefold())


def score(query, text, aliases):
    query, text = normalized(query), normalized(text)
    hits = [len(a) ** 2 for a in aliases if normalized(a) in query]
    # Continuous Chinese queries: character bigrams, not whitespace splitting.
    grams = {
        query[i : i + 2]
        for i in range(len(query) - 1)
        if re.fullmatch(r"[\u4e00-\u9fff]{2}", query[i : i + 2])
    }
    overlaps = sum(g in text for g in grams)
    return sum(hits) * 4 + overlaps if hits or overlaps >= 2 else 0


def passages(content):
    paragraphs = [p.strip() for p in re.split(r"\n+|(?<=[。！？])", content) if p.strip()]
    chunks, buffer = [], ""
    for paragraph in paragraphs:
        for start in range(0, len(paragraph), 800):
            part = paragraph[start : start + 800]
            if len(buffer) + len(part) > 800:
                chunks.append(buffer)
                buffer = ""
            buffer += part
    if buffer:
        chunks.append(buffer)
    return chunks


class WealthKnowledgeRetriever(Protocol):
    async def search(
        self, product_id: str | None, query: str, version_id: str | None = None
    ) -> list[WealthKnowledgeResult]: ...


class KeywordWealthKnowledge:
    def __init__(self, service):
        self.service = service

    async def fragments(self, query, product_id=None, version_id=None, *, include_education=True):
        ranked = []
        now = utc(self.service.clock()).isoformat()
        if product_id:
            version = await self.service.version(product_id, version_id)
            if version_id is None:
                from banking_api.wealth.design_profiles import design_evidence

                product = await self.service.product(product_id)
                design = design_evidence(product)
                if design:
                    relevance = score(
                        query,
                        design.title + design.content,
                        [
                            "策略",
                            "定位",
                            "收益来源",
                            "投资方向",
                            "风险",
                            "收益",
                            "增长",
                            "亏损",
                        ],
                    )
                    if relevance:
                        ranked.append((20000 + relevance, design))
            docs = await self.service.documents(version, historical=version_id is not None)
            for document in docs:
                if (
                    document.content_hash != digest(document.content)
                    or version.terms.get("document_hashes", {}).get(document.document_id)
                    != document.content_hash
                    or document.structured_terms != version.terms
                    or not safe_source(document.source, "PRODUCT")
                ):
                    continue
                for index, chunk in enumerate(passages(document.content)):
                    aliases = [
                        a
                        for group in ALIASES
                        if any(a in query for a in group)
                        and any(a in document.section + chunk for a in group)
                        for a in group
                    ]
                    relevance = score(query, document.section + chunk, aliases)
                    if relevance:
                        ranked.append(
                            (
                                10000 + relevance,
                                WealthEvidence(
                                    evidence_id=f"{document.document_id}:part:{index}",
                                    document_id=document.document_id,
                                    title=f"{version.name} · {document.section}",
                                    section=document.section,
                                    scope="PRODUCT",
                                    source_type="MOCK_PRODUCT",
                                    source_name="项目模拟产品资料",
                                    url=document.source,
                                    version=document.version,
                                    content_hash=document.content_hash,
                                    content=chunk,
                                    product_id=product_id,
                                    version_id=version.version_id,
                                    effective_from=utc(document.effective_from).isoformat(),
                                    effective_to=utc(document.effective_to).isoformat()
                                    if document.effective_to
                                    else None,
                                ),
                            )
                        )
        if include_education:
            for entry in education_entries():
                if entry.get("effective_from") and entry["effective_from"] > now[:10]:
                    continue
                if entry.get("effective_to") and entry["effective_to"] <= now[:10]:
                    continue
                relevance = score(query, entry["title"] + entry["content"], entry["aliases"])
                if relevance:
                    ranked.append(
                        (
                            relevance,
                            WealthEvidence(
                                evidence_id=entry["id"],
                                title=entry["title"],
                                section=entry["section"],
                                scope="EDUCATION",
                                source_type=entry["source_type"],
                                source_name=entry["source_name"],
                                url=entry["url"],
                                version=entry["version"],
                                content_hash=entry["content_hash"],
                                content=entry["content"],
                                verified_at=entry["verified_at"],
                                published_at=entry["published_at"],
                                effective_from=entry.get("effective_from"),
                                effective_to=entry.get("effective_to"),
                            ),
                        )
                    )
        ranked.sort(key=lambda row: (-row[0], row[1].evidence_id))
        return [row for _, row in ranked[:5]]

    async def search(self, product_id, query, version_id=None):
        # Existing product-only callers retain their contract and source scope.
        rows = await self.fragments(
            query, product_id, version_id, include_education=product_id is None
        )
        return [
            WealthKnowledgeResult(
                document_id=e.document_id or e.evidence_id,
                version=e.version,
                section=e.section,
                source=e.url,
                content=e.content,
            )
            for e in rows
        ]
