"""Validate and process a batch of payments atomically."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy import Engine

from db.transaction import transaction
from repositories.errors import PaymentRejected
from repositories.payments import PaymentRepository, PaymentWrite


MAX_AMOUNT_DOLLARS = Decimal("21474836.47")


@dataclass(frozen=True)
class PaymentInstruction:
    amount: str
    payee_firm_uuid: str
    description: str


class PaymentService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def bulk_update(self, payer_firm_uuid: str, payments: list[PaymentInstruction]) -> None:
        if not payments:
            raise PaymentRejected("empty_batch", "At least one payment is required")

        records: list[PaymentWrite] = [
            {
                "payee_firm_uuid": payment.payee_firm_uuid,
                "amount_cents": self._amount_cents(payment.amount),
                "description": payment.description,
            }
            for payment in payments
        ]

        with transaction(self.engine) as connection:
            repository = PaymentRepository(connection)
            repository.bulk_update(payer_firm_uuid, records)

    @staticmethod
    def _amount_cents(value: str) -> int:
        try:
            amount = Decimal(value)
        except InvalidOperation:
            raise PaymentRejected("invalid_amount", "Invalid payment amount") from None
        if (
            not amount.is_finite()
            or amount <= 0
            or amount > MAX_AMOUNT_DOLLARS
            or amount.as_tuple().exponent < -2
        ):
            raise PaymentRejected(
                "invalid_amount",
                "Amount must be positive, have at most two decimals, and fit INTEGER cents",
            )
        return int(amount * 100)
