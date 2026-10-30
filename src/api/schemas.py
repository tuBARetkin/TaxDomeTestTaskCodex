"""Request validation schemas for the payments API."""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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
        return value


class BulkPaymentRequest(BaseModel):
    payer_firm_uuid: UUID
    payments: Annotated[list[PaymentItem], Field(min_length=1)]
