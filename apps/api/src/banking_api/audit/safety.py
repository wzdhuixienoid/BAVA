"""Export only explicit evidence fields; untrusted strings are not executable facts."""

import re

from banking_api.config.settings import get_settings

_SENSITIVE = re.compile(
    r"authorization|bearer\s|cookie|api[ _-]?key|access[ _-]?token|jwt|"
    r"password|secret|otp|验证码|scratchpad|reasoning|chain[ _-]?of[ _-]?thought|"
    r"sk-[a-z0-9_-]+|eyJ[a-z0-9_-]+\.[a-z0-9_-]+\.[a-z0-9_-]+",
    re.IGNORECASE,
)


def safe_text(value: object) -> str:
    text = str(value)
    settings = get_settings()
    if _SENSITIVE.search(text) or any(
        secret and secret in text for secret in (settings.llm_api_key, settings.mock_reauth_code)
    ):
        return "[敏感内容已省略]"
    return text[:500]


def workflow_evidence(state: dict) -> dict:
    """Minimal persisted resolver/validation snapshot, never full state/Prompt/OTP."""
    draft = state.get("draft") or {}
    review = state.get("review_payload") or {}
    evidence = {
        key: safe_text(draft[key])
        for key in (
            "recipient_query",
            "amount",
            "currency",
            "source_account_hint",
            "payee_id",
            "source_account_id",
            "subscription_query",
            "subscription_id",
        )
        if draft.get(key) is not None
    }
    evidence.update(
        {
            key: safe_text(review[key])
            for key in (
                "source_account_display_name",
                "source_account_masked_number",
                "payee_display_name",
                "payee_masked_account",
                "merchant",
            )
            if review.get(key) is not None
        }
    )
    validation = state.get("validation")
    if validation:
        evidence["validation_valid"] = validation["is_valid"]
        evidence["validated_at"] = validation["validated_at"]
        evidence["validation_codes"] = [issue["code"] for issue in validation["issues"]]
    if state.get("error_code"):
        evidence["error_code"] = safe_text(state["error_code"])
    if "candidates" in state:
        evidence["subscriptions"] = [
            {
                key: safe_text(item[key]) if isinstance(item.get(key), str) else item.get(key)
                for key in (
                    "subscription_id",
                    "merchant",
                    "management_type",
                    "status",
                    "cancellable",
                )
            }
            for item in state["candidates"][:10]
        ]
    return evidence
