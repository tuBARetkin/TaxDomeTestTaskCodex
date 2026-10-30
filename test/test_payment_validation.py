"""Payment request validation and integer-cent boundary acceptance tests."""

from fastapi.testclient import TestClient
from sqlalchemy import text

from api.main import app
from test.database_case import DatabaseTestCase

PINECREST_UUID = "3f1c9a2e-7b4d-4c1e-9a55-2d8e6f0b7c41"
LOPEZ_UUID = "8b2e4c71-0d3a-4f6e-b1c9-5a7d2e9f4c10"
NAIR_UUID = "e5f18b3c-2a9d-4c07-8e6b-1d4a7f9c3b25"
INITIAL_BALANCES = ((1, 5_000_000), (2, 50_000), (3, 200_000))


class PaymentValidationTests(DatabaseTestCase):
    def assert_payment_state(self, expected_balances, expected_payments):
        with self.engine.connect() as connection:
            balances = connection.execute(
                text("SELECT id, balance_cents FROM firms ORDER BY id")
            ).all()
            payments = connection.execute(
                text(
                    "SELECT payer_firm_id, payee_firm_id, amount_cents, description "
                    "FROM payments"
                )
            ).all()

        self.assertEqual(balances, list(expected_balances))
        self.assertCountEqual(payments, expected_payments)

    def test_rejects_invalid_amounts(self):
        invalid_amounts = (
            "",
            "abc",
            "-1",
            "0",
            "0.00",
            "1.234",
            "1e2",
            "NaN",
            "Infinity",
            1,
            1.25,
        )
        with TestClient(app) as client:
            for amount in invalid_amounts:
                with self.subTest(amount=amount):
                    response = client.post(
                        "/api/v1/payments/",
                        json={
                            "payer_firm_uuid": PINECREST_UUID,
                            "payments": [
                                {
                                    "amount": amount,
                                    "payee_firm_uuid": LOPEZ_UUID,
                                    "description": "Invalid amount",
                                }
                            ],
                        },
                    )

                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(
                        [error["loc"] for error in response.json()["detail"]],
                        [["body", "payments", 0, "amount"]],
                    )
                    self.assert_payment_state(INITIAL_BALANCES, [])

    def test_rejects_empty_batch(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={"payer_firm_uuid": PINECREST_UUID, "payments": []},
            )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(
            [error["loc"] for error in response.json()["detail"]],
            [["body", "payments"]],
        )
        self.assert_payment_state(INITIAL_BALANCES, [])

    def test_rejects_invalid_firm_uuids(self):
        cases = (
            ("not-a-uuid", LOPEZ_UUID, ["body", "payer_firm_uuid"]),
            (PINECREST_UUID, "not-a-uuid", ["body", "payments", 0, "payee_firm_uuid"]),
        )
        with TestClient(app) as client:
            for payer_uuid, payee_uuid, expected_location in cases:
                with self.subTest(field=expected_location[-1]):
                    response = client.post(
                        "/api/v1/payments/",
                        json={
                            "payer_firm_uuid": payer_uuid,
                            "payments": [
                                {
                                    "amount": "1",
                                    "payee_firm_uuid": payee_uuid,
                                    "description": "Invalid firm UUID",
                                }
                            ],
                        },
                    )

                    self.assertEqual(response.status_code, 422, response.text)
                    self.assertEqual(
                        [error["loc"] for error in response.json()["detail"]],
                        [expected_location],
                    )
                    self.assert_payment_state(INITIAL_BALANCES, [])

    def test_rejects_payment_one_cent_above_integer_limit(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": PINECREST_UUID,
                    "payments": [
                        {
                            "amount": "21474836.48",
                            "payee_firm_uuid": LOPEZ_UUID,
                            "description": "Above individual amount limit",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "invalid_amount")
        self.assert_payment_state(INITIAL_BALANCES, [])

    def test_rejects_batch_total_one_cent_above_integer_limit(self):
        # Both payments fit INTEGER individually; together they exceed it by a cent.
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": PINECREST_UUID,
                    "payments": [
                        {
                            "amount": "21474836.47",
                            "payee_firm_uuid": LOPEZ_UUID,
                            "description": "At individual amount limit",
                        },
                        {
                            "amount": "0.01",
                            "payee_firm_uuid": NAIR_UUID,
                            "description": "One extra cent",
                        },
                    ],
                },
            )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "batch_amount_too_large")
        self.assert_payment_state(INITIAL_BALANCES, [])

    def test_accepts_payment_at_integer_limit(self):
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE firms SET balance_cents = 2147483647 WHERE id = 1")
            )
            # Leave room for the maximum credit without overflowing the recipient.
            connection.execute(text("UPDATE firms SET balance_cents = 0 WHERE id = 2"))

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": PINECREST_UUID,
                    "payments": [
                        {
                            "amount": "21474836.47",
                            "payee_firm_uuid": LOPEZ_UUID,
                            "description": "Maximum payment",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.assert_payment_state(
            [(1, 0), (2, 2_147_483_647), (3, 200_000)],
            [(1, 2, 2_147_483_647, "Maximum payment")],
        )

    def test_accepts_batch_total_at_integer_limit(self):
        with self.engine.begin() as connection:
            connection.execute(
                text("UPDATE firms SET balance_cents = 2147483647 WHERE id = 1")
            )
            connection.execute(text("UPDATE firms SET balance_cents = 0 WHERE id = 2"))

        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": PINECREST_UUID,
                    "payments": [
                        {
                            "amount": "21474836.46",
                            "payee_firm_uuid": LOPEZ_UUID,
                            "description": "All but one cent",
                        },
                        {
                            "amount": "0.01",
                            "payee_firm_uuid": NAIR_UUID,
                            "description": "Last cent",
                        },
                    ],
                },
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.assert_payment_state(
            [(1, 0), (2, 2_147_483_646), (3, 200_001)],
            [(1, 2, 2_147_483_646, "All but one cent"), (1, 3, 1, "Last cent")],
        )

    def test_transfers_exact_payer_balance(self):
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": LOPEZ_UUID,
                    "payments": [
                        {
                            "amount": "500",
                            "payee_firm_uuid": PINECREST_UUID,
                            "description": "Full balance",
                        }
                    ],
                },
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.content, b"")
        self.assert_payment_state(
            [(1, 5_050_000), (2, 0), (3, 200_000)],
            [(2, 1, 50_000, "Full balance")],
        )

    def test_stores_supported_amount_formats_as_exact_cents(self):
        amounts = (("1", 100), ("1.2", 120), ("1.23", 123), ("0.01", 1))
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/",
                json={
                    "payer_firm_uuid": PINECREST_UUID,
                    "payments": [
                        {
                            "amount": amount,
                            "payee_firm_uuid": LOPEZ_UUID,
                            "description": f"Amount {amount}",
                        }
                        for amount, _ in amounts
                    ],
                },
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.assert_payment_state(
            [(1, 4_999_656), (2, 50_344), (3, 200_000)],
            [(1, 2, cents, f"Amount {amount}") for amount, cents in amounts],
        )
