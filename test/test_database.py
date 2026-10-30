"""Exercise migrations and models against PostgreSQL in a rolled-back schema."""

import os
from pathlib import Path
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


@unittest.skipUnless(os.getenv("DATABASE_URL"), "DATABASE_URL is required")
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(os.environ["DATABASE_URL"])
        self.addCleanup(self.engine.dispose)
        self.connection = self.engine.connect()
        self.addCleanup(self.connection.close)
        transaction = self.connection.begin()
        self.addCleanup(transaction.rollback)
        schema = f"test_{uuid4().hex}"
        self.connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        self.connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
        root = Path(__file__).resolve().parents[1]
        self.config = Config(str(root / "alembic.ini"))
        self.config.attributes["connection"] = self.connection
        command.upgrade(self.config, "head")

    def test_models_store_firms_and_payment(self):
        from db.models import Firm, Payment

        with Session(self.connection, join_transaction_mode="create_savepoint") as session:
            payer = Firm(name="Payer", balance_cents=10000, uuid=str(uuid4()))
            payee = Firm(name="Payee", balance_cents=500, uuid=str(uuid4()))
            session.add_all([payer, payee])
            session.flush()
            payment = Payment(
                payer_firm_id=payer.id,
                payee_firm_id=payee.id,
                amount_cents=1250,
                description="Invoice payment",
            )
            session.add(payment)
            session.flush()
            payment_id = payment.id
            session.expire_all()
            stored = session.get(Payment, payment_id)
            self.assertEqual(stored.amount_cents, 1250)
            self.assertEqual(stored.description, "Invoice payment")
            self.assertEqual(stored.payer_firm_id, payer.id)
            self.assertEqual(stored.payee_firm_id, payee.id)

    def test_firm_public_identifier_is_unique(self):
        params = {"uuid": str(uuid4())}
        statement = text(
            "INSERT INTO firms (name, balance_cents, uuid) "
            "VALUES ('Firm', 0, :uuid)"
        )
        self.connection.execute(statement, params)
        with self.assertRaises(IntegrityError), self.connection.begin_nested():
            self.connection.execute(statement, params)

    def test_both_payment_firms_must_exist(self):
        firm_id = self.connection.execute(
            text("INSERT INTO firms (name, balance_cents, uuid) "
                 "VALUES ('Firm', 0, :uuid) RETURNING id"),
            {"uuid": str(uuid4())},
        ).scalar_one()
        for payer, payee in ((-1, firm_id), (firm_id, -1)):
            with self.subTest(payer=payer, payee=payee):
                with self.assertRaises(IntegrityError), self.connection.begin_nested():
                    self.connection.execute(
                        text("INSERT INTO payments "
                             "(payer_firm_id, payee_firm_id, amount_cents, description) "
                             "VALUES (:payer, :payee, 100, 'Test')"),
                        {"payer": payer, "payee": payee},
                    )

    def test_migration_can_be_reversed_and_reapplied(self):
        command.downgrade(self.config, "base")
        self.assertNotIn("payments", inspect(self.connection).get_table_names())
        self.assertNotIn("firms", inspect(self.connection).get_table_names())
        command.upgrade(self.config, "head")
        self.assertIn("firms", inspect(self.connection).get_table_names())
        self.assertIn("payments", inspect(self.connection).get_table_names())
