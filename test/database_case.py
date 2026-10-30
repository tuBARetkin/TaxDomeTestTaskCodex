"""Shared setup for a clean, seeded PostgreSQL test database."""

import os
from pathlib import Path
import unittest
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        database_url = os.environ.get("TEST_DATABASE_URL")
        if not database_url:
            raise RuntimeError("Set TEST_DATABASE_URL or use the Compose test service")

        url = make_url(database_url)
        if url.get_backend_name() != "postgresql" or url.database != "taxdome_test_task_test":
            raise RuntimeError("Tests may reset only the taxdome_test_task_test PostgreSQL database")

        self.engine = create_engine(url)
        self.addCleanup(self.engine.dispose)
        root = Path(__file__).resolve().parents[1]
        self.config = Config(str(root / "alembic.ini"))

        # Commit the reset and seed so the API's separate connections can see them.
        with self.engine.begin() as connection:
            connection.exec_driver_sql("DROP SCHEMA public CASCADE")
            connection.exec_driver_sql("CREATE SCHEMA public")
            self.config.attributes["connection"] = connection
            command.upgrade(self.config, "head")
        self.config.attributes.pop("connection")

        # The real app uses the dedicated test database during this test only.
        self.enterContext(patch.dict(os.environ, {"DATABASE_URL": database_url}))
