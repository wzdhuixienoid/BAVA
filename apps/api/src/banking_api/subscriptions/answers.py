SUBSCRIPTION_OVERVIEW_HINT = "详细信息可在左侧「订阅与代扣总览」查看。"


def subscription_answer(answer: str) -> str:
    return (
        f"{answer.replace(SUBSCRIPTION_OVERVIEW_HINT, '').rstrip()}\n\n{SUBSCRIPTION_OVERVIEW_HINT}"
    )
