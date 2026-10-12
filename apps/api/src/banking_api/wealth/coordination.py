"""Resolve only trusted, owner-scoped objects from a verified semantic frame."""

from banking_api.wealth.schemas import WealthAnalysisInput

ACTIONS = {
    "CATALOGUE": "CATALOGUE",
    "RECOMMEND": "RECOMMENDATION",
    "COMPARE": "COMPARISON",
    "EXPLAIN": "EXPLANATION",
    "KNOWLEDGE": "EDUCATION",
    "PREPARE_PURCHASE": "PREPARE_PURCHASE",
    "PREPARE_REDEEM": "PREPARE_REDEEM",
    "PRODUCT_OVERVIEW": "PRODUCT_OVERVIEW",
}


def analysis_request(frame, products, previous=None, accounts=()):
    ids = []
    for mention in frame.product_mentions:
        matches = [
            p.product_id
            for p in products
            if mention in p.name or p.name.removeprefix("演示") == mention
        ]
        if len(matches) == 1:
            ids.append(matches[0])
        else:
            frame.ambiguities.append("产品名称无法唯一确定")
    order = previous.candidates if previous and not frame.new_plan else []
    for token in frame.references:
        if token in {"这些", "这些产品", "这几款", "这几款产品", "它们", "上面这些", "上次那些"}:
            # Plural feedback describes the prior set; it is not a request to pick one.
            if frame.action in {"RECOMMEND", "CATALOGUE", "PRODUCT_OVERVIEW", "KNOWLEDGE"}:
                continue
            if frame.action == "COMPARE" and order:
                ids.extend(c.product.product_id for c in order[:4])
                continue
        if token in {"这个", "这款", "它"} and len(ids) == 1:
            continue
        index = {
            "第一款": 0,
            "第二款": 1,
            "第三款": 2,
            "第四款": 3,
            "第1款": 0,
            "第2款": 1,
            "第3款": 2,
            "第4款": 3,
            "首款": 0,
        }.get(token)
        if index is None and len(order) == 1:
            index = 0
        if index is None or index >= len(order):
            frame.ambiguities.append("请明确选择的产品名称")
        else:
            ids.append(order[index].product.product_id)
    if (
        not ids
        and frame.action.startswith("PREPARE_")
        and previous
        and previous.result_kind.startswith("PREPARE_")
        and len(order) == 1
    ):
        ids = [order[0].product.product_id]
    if frame.action == "COMPARE" and not frame.product_mentions and len(order) > 1:
        ids = (
            list(dict.fromkeys([order[0].product.product_id] + ids))
            if frame.references
            else [c.product.product_id for c in order[:4]]
        )
    amount = None
    money = [m for m in frame.quantity_mentions if m.role != "RESERVE" and m.unit == "元"]
    if len(money) == 1 and money[0].exact and not money[0].error:
        amount = money[0].value
    elif money:
        frame.ambiguities.append("请核对一个明确的投资金额")
    account_id = None
    if frame.account_mention:
        matches = [
            a["account_id"]
            for a in accounts
            if frame.account_mention in a["display_name"]
            or a["display_name"] in frame.account_mention
        ]
        if len(matches) == 1:
            account_id = matches[0]
        else:
            frame.ambiguities.append("请选择本人付款账户")
    if frame.action.startswith("PREPARE_"):
        if len(ids) != 1:
            frame.ambiguities.append("请选择一款产品")
        if (
            frame.quantity_mentions
            and any(m.unit == "份" for m in frame.quantity_mentions)
            and frame.action == "PREPARE_PURCHASE"
        ):
            frame.ambiguities.append("申购需要金额（元），不能用份额代替")
    return WealthAnalysisInput(
        intent=ACTIONS.get(frame.action, "RECOMMENDATION"),
        query=frame.source_text,
        needs=frame.source_text,
        product_ids=list(dict.fromkeys(ids)),
        amount=amount,
        account_id=account_id,
        intent_frame=frame,
    )
