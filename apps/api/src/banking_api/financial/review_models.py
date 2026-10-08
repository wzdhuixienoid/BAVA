from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SpendingReviewItem(BaseModel):
    transaction_id: str
    occurred_at: datetime
    merchant: str
    amount_display: str
    reason: str


class SpendingReview(BaseModel):
    status: Literal["REVIEWED", "PARTIAL", "UNAVAILABLE"]
    message: str
    notes: list[str] = Field(default_factory=list)
    items: list[SpendingReviewItem] = Field(default_factory=list, max_length=3)
    total_count: int = 0
    answer: str
