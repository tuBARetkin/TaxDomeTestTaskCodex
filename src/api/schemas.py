"""Request validation schemas for the payments API."""

from decimal import Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from db.limits import MAX_AMOUNT_CENTS
from repositories.errors import PaymentRejected

MAX_AMOUNT_DOLLARS = Decimal(MAX_AMOUNT_CENTS) / 100
MAX_PAYMENTS_PER_BATCH = 1_000


class PaymentItem(BaseModel):
    amount: Annotated[
        str,
        Field(strict=True, pattern=r"^[0-9]+(?:\.[0-9]{1,2})?$"),
    ]
    payee_firm_uuid: UUID
    description: str

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        amount = Decimal(value)
        if amount <= 0:
            raise ValueError("Amount must be positive")
        if amount > MAX_AMOUNT_DOLLARS:
            raise PaymentRejected(
                "invalid_amount",
                "Amount must be positive, have at most two decimals, and fit INTEGER cents",
            )
        return value

    @property
    def amount_cents(self) -> int:
        return int(Decimal(self.amount) * 100)


class BulkPaymentRequest(BaseModel):
    payer_firm_uuid: UUID
    payments: Annotated[
        list[PaymentItem], Field(min_length=1, max_length=MAX_PAYMENTS_PER_BATCH)
    ]

    @field_validator("payments", mode="before")
    @classmethod
    def validate_batch_size(cls, value: object) -> object:
        # Reject oversized JSON arrays before validating or converting their items.
        if isinstance(value, list) and len(value) > MAX_PAYMENTS_PER_BATCH:
            raise PaymentRejected(
                "batch_too_large",
                f"A batch may contain at most {MAX_PAYMENTS_PER_BATCH} payments",
            )
        return value

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if any(
            payment.payee_firm_uuid == self.payer_firm_uuid for payment in self.payments
        ):
            raise PaymentRejected(
                "self_transfer_not_allowed",
                "Payer and payee must be different firms",
            )
        if sum(payment.amount_cents for payment in self.payments) > MAX_AMOUNT_CENTS:
            raise PaymentRejected(
                "batch_amount_too_large",
                "The batch total exceeds the maximum supported firm balance",
            )
        return self
