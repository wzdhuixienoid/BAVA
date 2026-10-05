"""Strict currency grounding at extraction boundary; no FX or risk policy here."""

import re

_ALIASES = {
    "CNY": ("CNY", "RMB", "人民币", "元", "¥", "￥"),
    "USD": ("USD", "美元"),
    "EUR": ("EUR", "欧元"),
    "JPY": ("JPY", "日元"),
    "HKD": ("HKD", "港元", "港币"),
    "GBP": ("GBP", "英镑"),
    "AUD": ("AUD", "澳元"),
    "CAD": ("CAD", "加元"),
    "SGD": ("SGD", "新元"),
}


def canonicalize_currency(value: str | None, original: str) -> str | None:
    expressed = set()
    for code, aliases in _ALIASES.items():
        for alias in aliases:
            pattern = (
                r"(?<![美欧日港澳加新])元"
                if alias == "元"
                else rf"(?<![a-zA-Z]){alias}(?![a-zA-Z])"
                if alias.isascii() and alias.isalpha()
                else re.escape(alias)
            )
            if re.search(pattern, original, re.IGNORECASE):
                expressed.add(code)
    for token in re.findall(r"(?:\d[\d,.]*\s*)([A-Za-z]{3})(?![A-Za-z])", original):
        expressed.add("CNY" if token.upper() == "RMB" else token.upper())
    known_units = {alias for aliases in _ALIASES.values() for alias in aliases}
    for unit in re.findall(r"\d[\d,.]*\s*([\u4e00-\u9fff]{1,5}?[币元镑])", original):
        if unit not in known_units:
            raise ValueError("Unknown currency unit requires clarification")
    if len(expressed) > 1:
        raise ValueError("Ambiguous currency expressions require clarification")
    candidate = (value or "").strip()
    code = next(
        (
            code
            for code, aliases in _ALIASES.items()
            if candidate.upper() in {a.upper() for a in aliases}
        ),
        None,
    )
    if candidate and code is None:
        if not re.fullmatch(r"[A-Za-z]{3}", candidate):
            raise ValueError("Unknown currency expression")
        code = candidate.upper()
    if expressed:
        grounded = next(iter(expressed))
        if code is not None and code != grounded:
            raise ValueError("Extracted currency contradicts original request")
        return grounded
    if code is not None and code != "CNY":
        raise ValueError("Non-CNY currency has no original-message evidence")
    # Existing explicit default: no expressed currency -> selected account currency.
    return None
