import hashlib
import json

from banking_api.workflows.subscription_cancel.models import (
    SubscriptionCancelReviewPayload,
)


def canonicalize_subscription_cancel_payload(
    payload: SubscriptionCancelReviewPayload,
) -> dict[str, object]:
    return {
        "action": payload.action,
        "subscription_id": payload.subscription_id,
        "user_id": payload.user_id,
        "contract_version": payload.contract_version,
        "merchant": payload.merchant,
        "plan_name": payload.plan_name,
        "amount": format(payload.amount, "f"),
        "currency": payload.currency,
        "next_billing_at": payload.next_billing_at.isoformat() if payload.next_billing_at else None,
    }


def subscription_cancel_payload_hash(payload: SubscriptionCancelReviewPayload) -> str:
    canonical = json.dumps(
        canonicalize_subscription_cancel_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
