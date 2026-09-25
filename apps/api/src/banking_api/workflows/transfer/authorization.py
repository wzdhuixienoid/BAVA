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
    return {
        "amount": format(amount, ".2f"),
        "currency": review.currency.upper(),
        "payee_id": review.payee_id,
        "source_account_id": review.source_account_id,
    }


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
