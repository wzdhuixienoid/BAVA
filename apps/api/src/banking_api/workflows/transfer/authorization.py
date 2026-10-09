import hashlib
import json
from decimal import Decimal
from typing import Any

from banking_api.workflows.transfer.models import TransferReviewPayload


def canonicalize_transfer_payload(
    payload: TransferReviewPayload | dict[str, Any],
) -> dict[str, str]:
    review = (
        payload
        if isinstance(payload, TransferReviewPayload)
        else TransferReviewPayload.model_validate(payload)
    )
    amount = Decimal(review.amount).quantize(Decimal("0.01"))
    canonical = {
        "amount": format(amount, ".2f"),
        "currency": review.currency.upper(),
        "payee_id": review.payee_id,
        "source_account_id": review.source_account_id,
    }
    # Unchanged empty-remark payloads retain their historical approval hashes.
    if review.remark:
        canonical.update({"payload_version": "2", "remark": review.remark})
    if review.scheduled_for:
        from datetime import UTC

        canonical.update(
            {
                "payload_version": "3",
                "scheduled_for": review.scheduled_for.astimezone(UTC).isoformat(),
                "execute_deadline": review.execute_deadline.astimezone(UTC).isoformat(),
                "business_timezone": review.business_timezone,
                "payee_target_version": review.payee_target_version or "",
            }
        )
    if review.recurrence:
        canonical.update(
            {
                "payload_version": "5",
                "recurrence": json.dumps(
                    review.recurrence.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
                ),
            }
        )
    if review.aa_share_id:
        canonical.update(
            {
                "payload_version": "4",
                "aa_request_id": str(review.aa_request_id),
                "aa_share_id": str(review.aa_share_id),
                "destination_user_id": review.destination_user_id,
                "destination_account_id": review.destination_account_id,
            }
        )
    return canonical


def canonical_transfer_json(
    payload: TransferReviewPayload | dict[str, Any],
) -> str:
    return json.dumps(
        canonicalize_transfer_payload(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def transfer_payload_hash(
    payload: TransferReviewPayload | dict[str, Any],
) -> str:
    encoded = canonical_transfer_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
