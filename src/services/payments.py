"""Map validated payment requests and process each batch atomically."""

from sqlalchemy import Engine

from api.schemas import BulkPaymentRequest, PaymentItem
from db.transaction import transaction
from repositories.models import PaymentWrite
from repositories.payments import PaymentRepository


class PaymentService:
    def __init__(self, engine: Engine):
        self.engine = engine

    def bulk_update(self, request: BulkPaymentRequest) -> None:
        records = self._to_repository_models(request.payments)

        with transaction(self.engine) as connection:
            repository = PaymentRepository(connection)
            repository.bulk_update(str(request.payer_firm_uuid), records)

    def _to_repository_models(self, payments: list[PaymentItem]) -> list[PaymentWrite]:
        return [
            PaymentWrite(
                payee_firm_uuid=str(payment.payee_firm_uuid),
                amount_cents=payment.amount_cents,
                description=payment.description,
            )
            for payment in payments
        ]
