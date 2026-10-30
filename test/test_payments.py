"""Payments API acceptance tests."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from api.main import app
from test.database_case import DatabaseTestCase


class PaymentTests(DatabaseTestCase):
    def test_transfer_100_dollars_from_pinecrest_to_lopez(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": "3f1c9a2e-7b4d-4c1e-9a55-2d8e6f0b7c41",
                    "payments": [
                        {
                            "amount": "100",
                            "payee_firm_uuid": "8b2e4c71-0d3a-4f6e-b1c9-5a7d2e9f4c10",
                            "description": "Test payment",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 201, response.text)

        with self.engine.connect() as connection:
            balances = connection.execute(
                text("SELECT id, balance_cents FROM firms ORDER BY id")
            ).all()
            payments = connection.execute(
                text("SELECT payer_firm_id, payee_firm_id, amount_cents, description "
                     "FROM payments ORDER BY id")
            ).all()

        self.assertEqual(balances, [(1, 4_990_000), (2, 60_000), (3, 200_000)])
        self.assertEqual(payments, [(1, 2, 10_000, "Test payment")])

    def test_rejects_batch_when_total_exceeds_payer_balance(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": "3f1c9a2e-7b4d-4c1e-9a55-2d8e6f0b7c41",
                    "payments": [
                        {
                            "amount": "30000",
                            "payee_firm_uuid": "8b2e4c71-0d3a-4f6e-b1c9-5a7d2e9f4c10",
                            "description": "First payment",
                        },
                        {
                            "amount": "30000",
                            "payee_firm_uuid": "e5f18b3c-2a9d-4c07-8e6b-1d4a7f9c3b25",
                            "description": "Second payment",
                        },
                    ],
                },
            )

        self.assertEqual(response.status_code, 422, response.text)
        with self.engine.connect() as connection:
            balances = connection.execute(
                text("SELECT id, balance_cents FROM firms ORDER BY id")
            ).all()
            payment_count = connection.execute(text("SELECT COUNT(*) FROM payments")).scalar_one()

        self.assertEqual(balances, [(1, 5_000_000), (2, 50_000), (3, 200_000)])
        self.assertEqual(payment_count, 0)

    def test_denied_payer_update_rolls_back_an_earlier_payee_credit(self):
        # Payee ID 1 is updated before payer ID 2, whose $500 cannot cover $600.
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": "8b2e4c71-0d3a-4f6e-b1c9-5a7d2e9f4c10",
                    "payments": [
                        {
                            "amount": "600",
                            "payee_firm_uuid": "3f1c9a2e-7b4d-4c1e-9a55-2d8e6f0b7c41",
                            "description": "Insufficient funds",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 422, response.text)
        with self.engine.connect() as connection:
            balances = connection.execute(
                text("SELECT id, balance_cents FROM firms ORDER BY id")
            ).all()
            payment_count = connection.execute(text("SELECT COUNT(*) FROM payments")).scalar_one()

        self.assertEqual(balances, [(1, 5_000_000), (2, 50_000), (3, 200_000)])
        self.assertEqual(payment_count, 0)
