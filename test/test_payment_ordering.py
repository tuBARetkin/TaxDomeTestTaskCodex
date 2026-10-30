"""Balance update ordering must be checked before any SQL is executed."""

import unittest
from unittest.mock import Mock

from sqlalchemy import Connection

from repositories.payments import PaymentRepository


class PaymentOrderingTests(unittest.TestCase):
    def test_rejects_unordered_firm_ids_before_updating_any_balance(self):
        connection = Mock(spec=Connection)
        repository = PaymentRepository(connection)

        with self.assertRaisesRegex(
            ValueError, "Balance updates require firm IDs in ascending order"
        ):
            repository._update_balances(
                payer_id=1,
                total_cents=200,
                deltas={1: -200, 3: 100, 2: 100},
            )

        connection.execute.assert_not_called()
