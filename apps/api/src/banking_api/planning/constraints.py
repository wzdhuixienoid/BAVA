import re


def has_conditional_control(user_request: str) -> bool:
    return bool(
        re.search(
            r"如果|倘若|若余额|若每月|是否.*(?:达到|不少于|超过)|有没有达到|循环|否则|\b(if|unless|while|else)\b",
            user_request,
            re.IGNORECASE,
        )
    )


def condition_request_error(user_request: str) -> str | None:
    if re.search(r"否则|不然|\belse\b", user_request, re.IGNORECASE):
        return "PLAN_ELSE_UNSUPPORTED"
    if has_conditional_control(user_request) and re.search(
        r"天气|下雨|生日|地理|循环|(?<!不)小于|(?<!不)低于|(?<!大于)等于|\b(unless|while|weather|rain|and|or|less|equals)\b|并且|或者",
        user_request,
        re.IGNORECASE,
    ):
        return "PLAN_UNSUPPORTED_CONDITION"
    return None
