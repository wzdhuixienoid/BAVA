"""Immutable fictional design notes. Never overwrite v1 contracts or financial history.

These are authored simulation assumptions, not bank disclosures or actual portfolios.
Synthetic NAVs are generated independently, so allocations cannot predict their returns.
"""

from datetime import UTC, datetime

from banking_api.wealth.calculation import utc
from banking_api.wealth.catalog import digest
from banking_api.wealth.schemas import WealthDesignProfile, WealthEvidence

VERSION = "mock-design-v1"
PUBLISHED_AT = datetime(2026, 10, 12, tzinfo=UTC)
NOTICE = (
    "以下是项目新增的模拟设计画像，不是真实银行产品、实际持仓或收益预测。"
    "合成净值由独立程序生成，并非按该组合回测；配置比例不能用于预测模拟收益。"
    "建议观察期不是锁定期；申赎、费用和到账仍以原版本交易条款为准。"
)

# Positioning must be authored here, never inferred from names or R grades by a model.
DESIGNS = [
    {
        "positioning": "现金与短债为主，侧重较低波动和申请灵活性",
        "strategy": "以现金类工具和短久期利率债作为模拟底仓，尽量减少对权益市场的依赖。",
        "allocation": {"现金及货币市场工具": 70, "短久期利率债": 30},
        "return_sources": ["现金类工具的利息", "短债票息及价格变化"],
        "risk_drivers": ["利率变化", "再投资利率下降", "赎回现金异步到账"],
        "suitable_for": "主要考虑较低波动、需要较多申请窗口的资金；不是即时应急现金",
        "unsuitable_for": "追求显著权益增长、要求保本或即时提现",
        "observation_days": 30,
        "observation_label": "以一个月及以上作为观察参考，非必须持有期限",
        "growth_exposure": 0,
        "concentration": 0,
    },
    {
        "positioning": "债券票息为主、周开放的稳健型观察选项",
        "strategy": "利率债与分散信用债搭配，主要依靠债券收益来源；采用周一申请窗口。",
        "allocation": {"现金类工具": 15, "利率债": 55, "分散信用债": 30},
        "return_sources": ["债券票息", "债券价格变化"],
        "risk_drivers": ["利率上行导致债券价格承压", "信用利差扩大或违约", "错过周开放窗口"],
        "suitable_for": "能提前安排申赎、接受债券净值波动的资金",
        "unsuitable_for": "希望每天申请、急用钱或不能承受本金损失",
        "observation_days": 90,
        "observation_label": "建议按三个月及以上观察债券策略，非锁定期",
        "growth_exposure": 0,
        "concentration": 1,
    },
    {
        "positioning": "债券组合为主、日开放，兼顾票息与申请便利",
        "strategy": "分散配置利率债和信用债，保留现金缓冲；不设置权益增强仓位。",
        "allocation": {"现金类工具": 20, "利率债": 50, "分散信用债": 30},
        "return_sources": ["债券票息", "利率与信用利差变化带来的债券价格变化"],
        "risk_drivers": ["利率与信用风险", "净值阶段性回撤", "赎回到账等待"],
        "suitable_for": "接受债券波动，同时希望有日开放申请窗口的资金",
        "unsuitable_for": "将债券收益当作固定利息、追求较大权益增长或需要保本",
        "observation_days": 90,
        "observation_label": "建议按三个月及以上观察，非强制持有期限",
        "growth_exposure": 0,
        "concentration": 1,
    },
    {
        "positioning": "债券打底、适量权益增强，兼顾增长与波动的混合策略",
        "strategy": "用债券底仓搭配分散权益，增加权益相关收益来源，保留日开放安排。",
        "allocation": {"现金类工具": 10, "债券组合": 60, "分散权益": 30},
        "return_sources": ["债券票息及价格变化", "权益分红和价格变化"],
        "risk_drivers": ["债券和权益同时下跌", "权益市场波动", "信用与利率风险"],
        "suitable_for": "希望在债券基础上增加增长来源、能够承受阶段性亏损的中期资金",
        "unsuitable_for": "短期刚性用款、只接受极小波动或要求收益保证",
        "observation_days": 180,
        "observation_label": "建议按半年及以上观察，开放日仍可申请赎回",
        "growth_exposure": 30,
        "concentration": 1,
    },
    {
        "positioning": "混合配置、权益增强略多，以周开放安排换取不同的策略选择",
        "strategy": "债券底仓搭配分散权益，设计权益比重略高于均衡优选；每周一开放。",
        "allocation": {"现金类工具": 10, "债券组合": 55, "分散权益": 35},
        "return_sources": ["债券票息及价格变化", "权益分红和价格变化"],
        "risk_drivers": ["权益与债券共振下跌", "权益波动", "周开放与较高赎回费的取舍"],
        "suitable_for": "能安排周开放、希望了解混合增长策略的中期资金",
        "unsuitable_for": "为周开放支付较高费用却期待必然更高收益、急用钱或保本需求",
        "observation_days": 180,
        "observation_label": "建议按半年及以上观察，非锁定期",
        "growth_exposure": 35,
        "concentration": 1,
    },
    {
        "positioning": "分散权益主导的成长策略，增长参与度与波动承担均更大",
        "strategy": "以分散权益为主要模拟增长来源，债券和现金用于分散部分风险，日开放。",
        "allocation": {"现金类工具": 10, "债券组合": 30, "分散权益": 60},
        "return_sources": ["权益价格变化与分红", "债券票息"],
        "risk_drivers": ["权益市场持续下跌", "估值变化", "较长时间不能恢复的回撤"],
        "suitable_for": "有较长观察期、愿意承担明显净值波动且测评允许的成长资金",
        "unsuitable_for": "把部分亏损理解为只能承受极小回撤、近期刚性用款或保证盈利需求",
        "observation_days": 365,
        "observation_label": "建议按一年及以上观察，非承诺一年后盈利",
        "growth_exposure": 60,
        "concentration": 1,
    },
    {
        "positioning": "周开放的权益成长策略，更需要提前安排用款",
        "strategy": "以分散权益为主，设计权益比重略高于进取成长；采用每周五申请窗口。",
        "allocation": {"现金类工具": 5, "债券组合": 30, "分散权益": 65},
        "return_sources": ["权益价格变化与分红", "债券票息"],
        "risk_drivers": ["权益波动与深度回撤", "周开放等待", "相对较高交易费用"],
        "suitable_for": "长期观察成长资产、能提前安排周窗口且愿意承担明显亏损的资金",
        "unsuitable_for": "预算不足起购、急用钱、不能承受明显回撤或期待周开放必然提高收益",
        "observation_days": 365,
        "observation_label": "建议按一年及以上观察，非锁定期或收益保证",
        "growth_exposure": 65,
        "concentration": 1,
    },
    {
        "positioning": "主题权益集中配置，用更大波动承担换取主题增长参与度",
        "strategy": "以成长主题权益为主，保留少量分散权益、债券与现金；集中度较高。",
        "allocation": {"现金类工具": 10, "债券组合": 5, "分散权益": 15, "成长主题权益": 70},
        "return_sources": ["主题与权益价格变化", "权益分红及少量债券票息"],
        "risk_drivers": ["主题景气反转", "行业集中风险", "权益市场与估值波动", "深度或长期回撤"],
        "suitable_for": "已理解主题集中风险、有长期资金并具备相应测评的高波动策略观察",
        "unsuitable_for": "仅因最近涨幅较高就追涨、不能承受明显亏损、急用钱或要求最大损失保护",
        "observation_days": 730,
        "observation_label": "建议以两年及以上观察主题周期，非实际赎回限制",
        "growth_exposure": 85,
        "concentration": 3,
    },
]


def design_profile(product_id, product_version_id, now):
    if utc(now) < PUBLISHED_AT or product_version_id != f"{product_id}:v1":
        return None
    if not product_id.startswith("mock-wealth-"):
        return None
    try:
        index = int(product_id.rsplit("-", 1)[-1]) - 1
        if not 0 <= index < len(DESIGNS):
            return None
        data = dict(DESIGNS[index])
    except ValueError:
        return None
    if sum(data["allocation"].values()) != 100:
        raise ValueError("Invalid mock design allocation")
    data.update(
        version=VERSION,
        product_version_id=product_version_id,
        published_at=PUBLISHED_AT.isoformat(),
        notice=NOTICE,
        scenarios={
            "利率上行": "债券价格可能承压，短久期与现金部分通常相对少受长期利率变化影响。",
            "权益下跌": "权益比重与主题集中度越大，设计上的权益风险暴露越多；债券也不能保证对冲。",
            "突然用钱": "需要等待申赎和现金到账；周开放还需安排申请日期。",
        },
    )
    return WealthDesignProfile(**data, content_hash=digest(data))


def design_evidence(product):
    p = product.design_profile
    if p is None:
        return None
    allocation = "、".join(f"{asset}{weight}%" for asset, weight in p.allocation.items())
    content = "\n".join(
        [
            f"{product.name}模拟设计定位：{p.positioning}。",
            f"设计策略：{p.strategy} 目标组合：{allocation}。",
            "收益来源：" + "；".join(p.return_sources) + "。",
            "主要风险：" + "；".join(p.risk_drivers) + "。",
            f"适合观察：{p.suitable_for}。不适合：{p.unsuitable_for}。",
            p.observation_label + "。",
            "\n".join(f"{key}：{value}" for key, value in p.scenarios.items()),
            p.notice,
        ]
    )
    return WealthEvidence(
        evidence_id=f"design:{product.product_id}:{p.version}",
        title=f"{product.name} · 模拟设计画像",
        section="模拟设计画像",
        scope="DESIGN",
        source_type="MOCK_DESIGN",
        source_name="项目编写的模拟设计资料",
        url=f"/api/v1/wealth/product-profiles/{product.product_id}/{p.version}",
        version=p.version,
        content_hash=digest(content),
        content=content,
        product_id=product.product_id,
        version_id=product.version_id,
        published_at=p.published_at,
        effective_from=p.published_at,
    )
