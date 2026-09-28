import hashlib
import json

from banking_api.workflows.subscription_cancel.models import (
    SubscriptionCancelReviewPayload,
)


def canonicalize_subscription_cancel_payload(
    payload: SubscriptionCancelReviewPayload,
) -> dict[str, str]:
    return {
        "action": "SUBSCRIPTION_CANCEL",
        "subscription_id": payload.subscription_id,
        "user_id": payload.user_id,
    }


def subscription_cancel_payload_hash(payload: SubscriptionCancelReviewPayload) -> str:
    canonical = json.dumps(
        canonicalize_subscription_cancel_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
