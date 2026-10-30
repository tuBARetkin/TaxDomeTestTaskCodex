"""Plain-SQL persistence for bulk payments."""

from itertools import pairwise

from sqlalchemy import Connection, text

from repositories.errors import PaymentRejected
from repositories.models import PaymentWrite


MAX_PAYMENTS_PER_BATCH = 1_000


class PaymentRepository:
    def __init__(self, connection: Connection):
        self.connection = connection

    def bulk_update(
        self,
        payer_firm_uuid: str,
        payments: list[PaymentWrite],
    ) -> None:
        """Update firms in ID order, then insert payments in the caller's transaction.

        Rejections raise PaymentRejected so the caller rolls back the entire
        transaction, including earlier firm updates. This method never commits.
        """
        if not payments:
            raise PaymentRejected("empty_batch", "At least one payment is required")
        if len(payments) > MAX_PAYMENTS_PER_BATCH:
            raise PaymentRejected(
                "batch_too_large",
                f"A batch may contain at most {MAX_PAYMENTS_PER_BATCH} payments",
            )
        if any(payment.amount_cents <= 0 for payment in payments):
            raise PaymentRejected("invalid_amount", "Payment amounts must be positive")

        total_cents = sum(payment.amount_cents for payment in payments)
        # A firm's INTEGER balance cannot cover a larger batch.
        if total_cents > 2_147_483_647:
            raise PaymentRejected(
                "batch_amount_too_large",
                "The batch total exceeds the maximum supported firm balance",
            )

        requested_uuids = {payer_firm_uuid, *(payment.payee_firm_uuid for payment in payments)}
        ids_by_uuid = self._select_and_sort_firms(requested_uuids)
        if payer_firm_uuid not in ids_by_uuid:
            raise PaymentRejected("payer_not_found", "Payer firm was not found")
        if requested_uuids - ids_by_uuid.keys():
            raise PaymentRejected("payee_not_found", "One or more payee firms were not found")

        payer_id = ids_by_uuid[payer_firm_uuid]
        deltas = self._calculate_deltas(payer_id, total_cents, payments, ids_by_uuid)
        self._update_balances(payer_id, total_cents, deltas)

        self._confirm_payments(payer_id, payments, ids_by_uuid)

    def _select_and_sort_firms(self, uuids: set[str]) -> dict[str, int]:
        firms = self.connection.execute(
            text("SELECT id, uuid FROM firms WHERE uuid = ANY(:firm_uuids) ORDER BY id"),
            {"firm_uuids": sorted(uuids)},
        ).mappings().all()
        return {firm["uuid"]: firm["id"] for firm in firms}

    @staticmethod
    def _calculate_deltas(
        payer_id: int,
        total_cents: int,
        payments: list[PaymentWrite],
        ids_by_uuid: dict[str, int],
    ) -> dict[int, int]:
        # Preserve the ascending ID order returned by _select_and_sort_firms.
        deltas = {firm_id: 0 for firm_id in ids_by_uuid.values()}
        deltas[payer_id] = -total_cents
        for payment in payments:
            payee_id = ids_by_uuid[payment.payee_firm_uuid]
            deltas[payee_id] += payment.amount_cents
        return deltas

    def _update_balances(
        self,
        payer_id: int,
        total_cents: int,
        deltas: dict[int, int],
    ) -> None:
        if any(previous > current for previous, current in pairwise(deltas)):
            raise ValueError("Balance updates require firm IDs in ascending order")

        update_firm = text(
            """
            UPDATE firms
            SET balance_cents = balance_cents + :delta_cents
            WHERE id = :firm_id
              AND (id <> :payer_id OR balance_cents >= :total_cents)
            RETURNING id
            """
        )
        # Separate statements guarantee this path acquires update locks in ID order.
        for firm_id, delta_cents in deltas.items():
            updated_id = self.connection.execute(
                update_firm,
                {
                    "firm_id": firm_id,
                    "payer_id": payer_id,
                    "total_cents": total_cents,
                    "delta_cents": delta_cents,
                },
            ).scalar_one_or_none()
            if updated_id is None:
                if firm_id == payer_id:
                    # A failed conditional update can also mean the payer was deleted.
                    existing_payer_id = self.connection.execute(
                        text("SELECT id FROM firms WHERE id = :payer_id"),
                        {"payer_id": payer_id},
                    ).scalar_one_or_none()
                    if existing_payer_id is None:
                        raise PaymentRejected("payer_not_found", "Payer firm was not found")
                    raise PaymentRejected(
                        "insufficient_funds",
                        "Payer has insufficient funds for the complete batch",
                    )
                raise PaymentRejected(
                    "payee_not_found",
                    f"Payee firm {firm_id} no longer exists",
                )

    def _confirm_payments(
        self,
        payer_id: int,
        payments: list[PaymentWrite],
        ids_by_uuid: dict[str, int],
    ) -> None:
        records = [
            {
                "payer_firm_id": payer_id,
                "payee_firm_id": ids_by_uuid[payment.payee_firm_uuid],
                "amount_cents": payment.amount_cents,
                "description": payment.description,
            }
            for payment in payments
        ]
        records.sort(key=lambda record: record["payee_firm_id"])
        self.connection.execute(
            text(
                """
                INSERT INTO payments
                    (payer_firm_id, payee_firm_id, amount_cents, description)
                VALUES
                    (:payer_firm_id, :payee_firm_id, :amount_cents, :description)
                """
            ),
            records,
        )
