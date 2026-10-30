"""Validate and process a batch of payments atomically."""

from decimal import Decimal, InvalidOperation

from sqlalchemy import Engine

from api.schemas import BulkPaymentRequest, PaymentItem
from db.transaction import transaction
from repositories.errors import PaymentRejected
from repositories.models import PaymentWrite
from repositories.payments import PaymentRepository


MAX_AMOUNT_DOLLARS = Decimal("21474836.47")


class PaymentService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def bulk_update(self, request: BulkPaymentRequest) -> None:
        if not request.payments:
            raise PaymentRejected("empty_batch", "At least one payment is required")
        if any(
            payment.payee_firm_uuid == request.payer_firm_uuid
            for payment in request.payments
        ):
            raise PaymentRejected(
                "self_transfer_not_allowed",
                "Payer and payee must be different firms",
            )

        records = self._to_repository_models(request.payments)

        with transaction(self.engine) as connection:
            repository = PaymentRepository(connection)
            repository.bulk_update(str(request.payer_firm_uuid), records)

    def _to_repository_models(self, payments: list[PaymentItem]) -> list[PaymentWrite]:
        return [
            PaymentWrite(
                payee_firm_uuid=str(payment.payee_firm_uuid),
                amount_cents=self._amount_cents(payment.amount),
                description=payment.description,
            )
            for payment in payments
        ]

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
