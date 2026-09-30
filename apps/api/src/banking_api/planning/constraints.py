import re


def has_conditional_control(user_request: str) -> bool:
    normalized = "".join(user_request.casefold().split())
    return any(marker in normalized for marker in ("如果", "若余额", "倘若", "循环")) or bool(
        re.search(r"\b(if|unless|while)\b", user_request, re.IGNORECASE)
    )
