"""Invalid payment input must be rejected before the service is called."""

import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.main import app

PINECREST_UUID = "3f1c9a2e-7b4d-4c1e-9a55-2d8e6f0b7c41"
LOPEZ_UUID = "8b2e4c71-0d3a-4f6e-b1c9-5a7d2e9f4c10"
NAIR_UUID = "e5f18b3c-2a9d-4c07-8e6b-1d4a7f9c3b25"


class EarlyPaymentValidationTests(unittest.TestCase):
    def setUp(self):
        # Lifespan creates an engine, but these requests must never connect to it.
        self.enterContext(
            patch.dict(
                os.environ,
                {"DATABASE_URL": "postgresql+psycopg://unused@127.0.0.1:1/unused"},
            )
        )
        self.service = self.enterContext(
            patch(
                "api.payments.PaymentService",
                side_effect=AssertionError("Invalid input reached the payment service"),
            )
        )
        self.client = self.enterContext(TestClient(app, raise_server_exceptions=False))

    def test_rejects_payment_rules_before_calling_service(self):
        cases = (
            ("invalid_amount", [("21474836.48", LOPEZ_UUID)]),
            ("self_transfer_not_allowed", [("1", PINECREST_UUID)]),
            ("batch_too_large", [("1", LOPEZ_UUID)] * 1_001),
            (
                "batch_amount_too_large",
                [("21474836.47", LOPEZ_UUID), ("0.01", NAIR_UUID)],
            ),
        )
        for code, payments in cases:
            with self.subTest(code=code):
                response = self.client.post(
                    "/api/v1/payments/",
                    json={
                        "payer_firm_uuid": PINECREST_UUID,
                        "payments": [
                            {
                                "amount": amount,
                                "payee_firm_uuid": payee_uuid,
                                "description": "Rejected before service",
                            }
                            for amount, payee_uuid in payments
                        ],
                    },
                )

                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(response.json()["detail"]["code"], code)
                self.service.assert_not_called()

    def test_checks_batch_size_before_validating_payment_items(self):
        response = self.client.post(
            "/api/v1/payments/",
            json={"payer_firm_uuid": PINECREST_UUID, "payments": [{}] * 1_001},
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIsInstance(response.json()["detail"], dict)
        self.assertEqual(response.json()["detail"]["code"], "batch_too_large")
        self.service.assert_not_called()

    def test_preserves_schema_error_format_when_fields_are_invalid(self):
        response = self.client.post(
            "/api/v1/payments/",
            json={
                "payer_firm_uuid": "not-a-uuid",
                "payments": [
                    {
                        "amount": "21474836.48",
                        "payee_firm_uuid": LOPEZ_UUID,
                        "description": "Invalid UUID and amount limit",
                    }
                ],
            },
        )

        self.assertEqual(response.status_code, 422, response.text)
        self.assertIsInstance(response.json()["detail"], list)
        self.assertIn(
            ["body", "payer_firm_uuid"],
            [error["loc"] for error in response.json()["detail"]],
        )
        self.service.assert_not_called()
