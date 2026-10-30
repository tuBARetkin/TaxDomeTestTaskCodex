# TaxDome Test Task

A backend test assignment for TaxDome: build a web service that receives bulk
payment requests from a single firm and processes them against firm balances.

## Goal and required behavior

For each request to `POST /api/v1/payments/`, the paying firm must have enough
funds to cover **all payments in the batch**.

- **Denied — HTTP `422`:** if the request is denied, including when the payer
  has insufficient funds, reject the entire batch. No payments or balance
  changes should be saved.
- **Created — HTTP `201`:** otherwise, add each payment to the database, debit
  the paying firm's balance, and credit each receiving firm's balance. These
  changes must succeed together as one transaction.

Request amounts are US dollars expressed as strings with at most two decimal
places. Database amounts and balances are stored as integer US cents.

## Current status

This commit is the initial application draft, not the completed assignment.
It contains the layered project structure, request validation, SQLAlchemy models,
Alembic migrations, and Docker Compose configuration.

The payment endpoint currently returns `501 Not Implemented` for a valid request.
The service and repository layers are placeholders; balance validation and
payment processing are still to be implemented. Tests and end-to-end checks of
this draft are deferred.

## Stack

Python 3.13, FastAPI, Uvicorn, SQLAlchemy, Alembic, Psycopg 3, and PostgreSQL 17.
Setuptools is the build dependency; tests use Python's built-in `unittest`.

## Run with Docker

Requires Docker with Docker Compose (included in Docker Desktop).

```sh
docker compose up --build
```

This starts PostgreSQL 17, waits until it is ready, applies Alembic migrations,
and starts the FastAPI app. No local Python, PostgreSQL, or configuration files
are required. The first run downloads images and Python packages.

- API docs: http://localhost:8000/docs
- Database health check: http://localhost:8000/health

The app provides a database health endpoint and a draft bulk payments endpoint.
To use a different host port, run
`APP_PORT=8001 docker compose up --build`.

The database uses the local review credentials `taxdome` / `taxdome` and database
`taxdome_test_task`. Its port is only accessible within the Compose network.
Inspect it with:

```sh
docker compose exec db psql -U taxdome -d taxdome_test_task
```

Stop the containers with `docker compose down`. Data persists in a named volume.
To explicitly delete the local database and start fresh, use
`docker compose down --volumes`.

On Colima/Homebrew installations that provide the standalone Compose command,
use `docker-compose` in place of `docker compose`.

## Database schema

- `firms`: `id INTEGER`, `name TEXT`, `balance_cents INTEGER`, `uuid TEXT`.
- `payments`: `id INTEGER`, `payer_firm_id INTEGER`, `payee_firm_id INTEGER`,
  `amount_cents INTEGER`, `description TEXT`.

All fields are required. IDs are generated primary keys, firm UUIDs are unique,
and both payment firm IDs reference `firms.id`. Amounts remain integer US cents.
Alembic also creates its `alembic_version` bookkeeping table.

## Seed data

Migration `0003` inserts the assignment's three firms:

| ID | Name | Balance (US cents) | UUID |
| --- | --- | ---: | --- |
| 1 | Pinecrest CPA Group | 5000000 | `3f1c9a2e-7b4d-4c1e-9a55-2d8e6f0b7c41` |
| 2 | Lopez Bookkeeping | 50000 | `8b2e4c71-0d3a-4f6e-b1c9-5a7d2e9f4c10` |
| 3 | Nair Tax Services | 200000 | `e5f18b3c-2a9d-4c07-8e6b-1d4a7f9c3b25` |

The seed runs once with `alembic upgrade head`, including during container startup.
It does not reset balances on later restarts. The firm ID sequence is advanced
after insertion so new firms can receive generated IDs without colliding with
the seed rows.

## Bulk payments API (draft)

`POST /api/v1/payments/`

```json
{
  "payer_firm_uuid": "3f1c9a2e-7b4d-4c1e-9a55-2d8e6f0b7c41",
  "payments": [
    {
      "amount": "1200.75",
      "payee_firm_uuid": "8b2e4c71-0d3a-4f6e-b1c9-5a7d2e9f4c10",
      "description": "Bookkeeping cleanup, 3 clients"
    },
    {
      "amount": "300",
      "payee_firm_uuid": "e5f18b3c-2a9d-4c07-8e6b-1d4a7f9c3b25",
      "description": "Referral fee, 2 clients"
    }
  ]
}
```

The endpoint currently validates the request body only:

- `payer_firm_uuid` and each `payee_firm_uuid` must be valid UUIDs.
- `payments` must contain at least one entry.
- `amount` must be a positive string with zero, one, or two decimal places.
- Each payment requires a string `description`.

Invalid input returns `422`. Valid input returns `501 Not Implemented` with
`{"detail": "Payment processing is not implemented yet"}`. The endpoint does not
query firms, create payments, or update balances. Service and database processing
will be added later. This draft has not been checked yet.

## Migrations

Migrations run automatically when the app container starts. To apply them manually:

```sh
docker compose exec app alembic upgrade head
```

## Local Python development

Requires Python 3.13 or newer and an accessible PostgreSQL database.

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
export DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/database'
alembic upgrade head
uvicorn api.main:app --reload
```

## Structure

```text
src/
  api/           FastAPI entry point, routes, and request schemas
  services/      Business logic (placeholder)
  repositories/  Database access (placeholder)
  db/            SQLAlchemy models and database infrastructure
test/            Database integration tests
migrations/      Alembic database migrations
compose.yaml     App and PostgreSQL containers
pyproject.toml   Package metadata and build configuration
```

## Tests

```sh
docker compose --profile test run --build --rm test
```

This builds the test runner with the optional HTTPX dependency and starts a
separate PostgreSQL container, `db-test`. It uses the database
`taxdome_test_task_test`, separate credentials, and temporary in-memory storage.
The application database and its persistent volume are not used by tests.

Before **each test**, the shared fixture recreates the test database's `public`
schema and applies every Alembic migration, including the three default firms.
Both the API and the test assertions use this database. The fixture requires
`TEST_DATABASE_URL` and refuses to reset a database with any other name.
Run the suite sequentially; concurrent runs must not share this test database.

The happy-path test posts a $100 payment from Pinecrest to Lopez and expects:

- HTTP `201`.
- Pinecrest balance: `4990000` cents; Lopez balance: `60000` cents.
- Nair balance unchanged at `200000` cents.
- One payment record for `10000` cents from firm `1` to firm `2`.

The suite also covers migrations, model persistence, UUID uniqueness, and payment
foreign keys. Tests have not been run yet. The happy-path test is expected to
fail until payment processing replaces the endpoint's `501` placeholder.

For local execution, provision a PostgreSQL database named
`taxdome_test_task_test`, then:

```sh
python -m pip install -e '.[test]'
export TEST_DATABASE_URL='postgresql+psycopg://user:password@localhost:5432/taxdome_test_task_test'
python -m unittest discover -s test -v
```

To remove only the test database container after testing:

```sh
docker compose --profile test rm --stop --force db-test
```
