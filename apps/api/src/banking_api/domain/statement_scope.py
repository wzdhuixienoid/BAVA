"""Ground explicit statement directions and continuation filters before tool validation."""

import re
from typing import Any


def statement_arguments(arguments: Any, text: str, *, continuation: dict | None = None) -> Any:
    if not isinstance(arguments, dict):
        return arguments  # Let the ToolExecutor return its normal validation error.
    if continuation:
        # Keep unknown model keys so grounding cannot bypass strict argument validation.
        return (
            arguments
            | continuation["filters"]
            | {
                "as_of": continuation["as_of"],
                "offset": continuation["next_offset"],
            }
        )
    compact = "".join(text.split())
    incoming = bool(re.search(r"转入|收入|收到|收过|转给我|给我转", compact))
    outgoing_text = re.sub(r"转给我|给我转(?:账|帐)?", "", compact)
    outgoing = bool(
        re.search(r"转出|支出|转给|(?:向|给)[^，。；,;]{1,24}(?:转|汇款|打款)", outgoing_text)
    )
    if incoming != outgoing:
        return arguments | {"direction": "CREDIT" if incoming else "DEBIT"}
    # Both directions or neither: leave per-query selection to the caller.
    return arguments
