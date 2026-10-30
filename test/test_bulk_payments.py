"""Bulk payment acceptance tests against the dedicated PostgreSQL database."""

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import text

from api.main import app
from test.database_case import DatabaseTestCase


PAYER_UUID = "3f1c9a2e-7b4d-4c1e-9a55-2d8e6f0b7c41"
LOPEZ_UUID = "8b2e4c71-0d3a-4f6e-b1c9-5a7d2e9f4c10"
NAIR_UUID = "e5f18b3c-2a9d-4c07-8e6b-1d4a7f9c3b25"


class BulkPaymentTests(DatabaseTestCase):
    def test_transfers_1000_payments_to_20_firms(self):
        # Each recipient starts with $100 and receives 50 payments.
        # Fixture columns: firm ID, dollar amount, cents, final balance in cents.
        recipients = [
            (4, "1.25", 125, 16_250),
            (5, "2.25", 225, 21_250),
            (6, "3.25", 325, 26_250),
            (7, "4.25", 425, 31_250),
            (8, "5.25", 525, 36_250),
            (9, "6.25", 625, 41_250),
            (10, "7.25", 725, 46_250),
            (11, "8.25", 825, 51_250),
            (12, "9.25", 925, 56_250),
            (13, "10.25", 1_025, 61_250),
            (14, "11.25", 1_125, 66_250),
            (15, "12.25", 1_225, 71_250),
            (16, "13.25", 1_325, 76_250),
            (17, "14.25", 1_425, 81_250),
            (18, "15.25", 1_525, 86_250),
            (19, "16.25", 1_625, 91_250),
            (20, "17.25", 1_725, 96_250),
            (21, "18.25", 1_825, 101_250),
            (22, "19.25", 1_925, 106_250),
            (23, "20.25", 2_025, 111_250),
        ]
        with self.engine.begin() as connection:
            connection.execute(
                text("INSERT INTO firms (id, name, balance_cents, uuid) "
                     "VALUES (:id, :name, 10000, :uuid)"),
                [
                    {"id": firm_id, "name": f"Recipient {firm_id}", "uuid": str(UUID(int=firm_id))}
                    for firm_id, _, _, _ in recipients
                ],
            )

        payments = []
        expected_payments = []
        # Interleave recipients in an order different from their integer IDs.
        request_order = recipients[::2] + recipients[1::2]
        for installment in range(50):
            for firm_id, amount, amount_cents, _ in request_order:
                description = f"Installment {installment + 1} for firm {firm_id}"
                payments.append(
                    {
                        "amount": amount,
                        "payee_firm_uuid": str(UUID(int=firm_id)),
                        "description": description,
                    }
                )
                expected_payments.append((1, firm_id, amount_cents, description))

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={"payer_firm_uuid": PAYER_UUID, "payments": payments},
            )

        self.assertEqual(response.status_code, 201, response.text)
        with self.engine.connect() as connection:
            balances = connection.execute(
                text("SELECT id, balance_cents FROM firms ORDER BY id")
            ).all()
            stored_payments = connection.execute(
                text("SELECT payer_firm_id, payee_firm_id, amount_cents, description FROM payments")
            ).all()

        # The batch totals $10,750; Pinecrest starts with $50,000.
        expected_balances = [(1, 3_925_000), (2, 50_000), (3, 200_000)]
        expected_balances.extend(
            (firm_id, final_balance) for firm_id, _, _, final_balance in recipients
        )
        self.assertEqual(balances, expected_balances)
        self.assertEqual(len(stored_payments), 1_000)
        self.assertCountEqual(stored_payments, expected_payments)

    def test_rejects_entire_batch_when_one_payee_is_missing(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": PAYER_UUID,
                    "payments": [
                        {"amount": "100", "payee_firm_uuid": LOPEZ_UUID, "description": "Lopez payment"},
                        {
                            "amount": "25.50",
                            "payee_firm_uuid": "00000000-0000-0000-0000-000000000000",
                            "description": "Missing recipient",
                        },
                        {"amount": "200", "payee_firm_uuid": NAIR_UUID, "description": "Nair payment"},
                    ],
                },
            )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "payee_not_found")
        with self.engine.connect() as connection:
            balances = connection.execute(
                text("SELECT id, balance_cents FROM firms ORDER BY id")
            ).all()
            payment_count = connection.execute(text("SELECT COUNT(*) FROM payments")).scalar_one()

        self.assertEqual(balances, [(1, 5_000_000), (2, 50_000), (3, 200_000)])
        self.assertEqual(payment_count, 0)

    def test_rejects_1001_payments(self):
        # $1,001 is affordable, and every recipient exists: only the count is invalid.
        payments = [
            {"amount": "1", "payee_firm_uuid": LOPEZ_UUID, "description": f"Payment {index + 1}"}
            for index in range(1_001)
        ]
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={"payer_firm_uuid": PAYER_UUID, "payments": payments},
            )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "batch_too_large")
        with self.engine.connect() as connection:
            balances = connection.execute(
                text("SELECT id, balance_cents FROM firms ORDER BY id")
            ).all()
            payment_count = connection.execute(text("SELECT COUNT(*) FROM payments")).scalar_one()

        self.assertEqual(balances, [(1, 5_000_000), (2, 50_000), (3, 200_000)])
        self.assertEqual(payment_count, 0)
