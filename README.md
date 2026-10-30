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

This is an application draft, not a verified submission.
It contains the layered project structure, request validation, SQLAlchemy models,
Alembic migrations, and Docker Compose configuration.

The payment endpoint is connected to a payment service and a plain-SQL repository.
The service converts amounts and owns the transaction. The repository updates
firm balances in ascending ID order, then inserts payment records. The $100
Pinecrest-to-Lopez API test passes against the isolated PostgreSQL database in
Docker. The remaining tests and concurrency checks are still deferred.

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

The payment flow uses two model layers:

- API models (`api/schemas.py`) validate the JSON request, including dollar
  strings and UUIDs.
- Repository models (`repositories/models.py`) carry integer cents and string
  UUIDs for persistence.

`PaymentService._to_repository_models()` maps between them. There is no separate
service model; the controller passes the API request to the service directly.

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

Request validation:

- `payer_firm_uuid` and each `payee_firm_uuid` must be valid UUIDs.
- `payments` must contain at least one entry.
- `amount` must be a positive string with zero, one, or two decimal places.
- Each payment requires a string `description`.

The service converts dollar strings to integer cents without floating-point
arithmetic. Invalid input or an amount exceeding the INTEGER range returns `422`.
`PaymentRepository.bulk_update()` in `src/repositories/payments.py` receives the
payer UUID, payment entries with integer cents, and an open SQLAlchemy Core
connection. All statements use that connection and bound parameters.

The repository looks up firm IDs without reading balances, aggregates balance
deltas, and executes one `UPDATE` per affected firm in ascending ID order. Each
update uses `balance_cents + delta_cents`: a negative delta debits the payer and
positive deltas credit payees. The payer update requires the current balance to
cover the entire batch, preventing the debit from taking it below zero. Payees
receive positive credits. Repeated payees share one balance update but retain
separate payment records.

Payment records are sorted by payee firm ID and inserted only after every firm
update succeeds. If any update affects no row, the batch is denied and all earlier
updates are rolled back. The lookup, individual updates, and batch insert are
separate SQL executions within the same transaction.

The repository completes normally on success and raises `PaymentRejected` on
denial, carrying an error code and message. The exception leaves the transaction
scope, rolling back all changes before the controller returns `422`. Success
returns `201` with an empty body. For example:

```json
{
  "detail": {
    "code": "insufficient_funds",
    "message": "Payer has insufficient funds for the complete batch"
  }
}
```

Other rejection codes include `empty_batch`, `batch_too_large`, `invalid_amount`,
`batch_amount_too_large`, `payer_not_found`, and `payee_not_found`. Request-schema
validation errors retain FastAPI's standard `422` response format.

Insufficient balance returns `insufficient_funds`; a missing payer returns
`payer_not_found`. Both use HTTP `422` and roll back the entire batch. If the
payer's conditional update affects no rows, an additional existence query
distinguishes these cases, including a payer deleted after the initial lookup.

Transaction isolation is explicitly set before beginning the transaction in
`src/db/transaction.py`; change `PAYMENT_ISOLATION_LEVEL` there. The current
setting is `READ COMMITTED`. There is no `SELECT FOR UPDATE`; the ordered updates
take PostgreSQL's normal row locks. The ordering avoids reverse-order locking
between batches following this path, but is not a guarantee against deadlocks
involving other write paths. Concurrent-request behavior has not been tested yet.

## Known limitations

- **Single PostgreSQL database.** All firms and payments live in one PostgreSQL
  database, so each transfer can update both parties and insert payment records
  in one local transaction. Sharding firms across multiple databases and
  cross-shard transfers are outside the scope of this test task. Whether a real
  tax service needs sharding should be decided from measured workload and
  scaling requirements; this implementation does not assume it is necessary.
- **Maximum 1,000 payments per batch.** `PaymentRepository.bulk_update()` rejects
  larger batches before iterating over payments or executing SQL. The controller
  translates this denial into HTTP `422`; no payments or balance changes are
  saved. The limit is defined by `MAX_PAYMENTS_PER_BATCH` in
  `src/repositories/payments.py`.
- **In-memory processing.** The request, service inputs, and insert records are
  held in memory. Aggregation visits every payment, and records are sorted before
  insertion. This implementation is intended for bounded batches, not millions
  of payments in one request. The repository limit does not limit HTTP body
  bytes or prevent earlier JSON parsing and service-side allocations; a request
  body size limit and streamed ingestion are not implemented.
- **32-bit INTEGER columns.** IDs, balances, and payment amounts use PostgreSQL
  `INTEGER`, whose range is `-2147483648` to `2147483647`. For money stored in
  cents, the maximum positive value is **$21,474,836.47**. Individual payments
  above this amount are rejected with `422`.
- **Batch totals.** Each payment can fit within INTEGER while their sum exceeds
  its maximum. Python's integer sum does not overflow, but the repository
  explicitly rejects totals above `2147483647` cents with `422`: a single firm's
  INTEGER balance cannot cover a larger batch.
- **Crediting a balance can overflow.** An individually valid payment and batch
  total do not guarantee that the recipient's existing balance plus its total
  credits fits INTEGER. For example, adding one cent to a balance of
  `2147483647` cents exceeds the limit. The SQL uses direct integer arithmetic,
  so this can raise a database overflow error. The error rolls back the whole transaction, but is not
  currently translated into `422` and can result in HTTP `500`. No wider-type
  casts or schema changes are implemented for this case.

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
  services/      Payment validation and transaction orchestration
  repositories/  Ordered balance updates and payment inserts in plain SQL
  db/            SQLAlchemy models and database infrastructure
test/            Database integration tests
migrations/      Alembic database migrations
compose.yaml     App and PostgreSQL containers
pyproject.toml   Package metadata and build configuration
```

## Tests

SQL logging is enabled by the test fixture for database setup, migrations, API
queries, and test assertions. SQLAlchemy prints statements, bound parameters,
and transaction boundaries to the test output. The fixture restores the previous
environment after each test. Normal app SQL logging defaults to off, and the
app's Compose configuration explicitly sets `SQL_ECHO=false`.

```sh
docker compose --profile test run --build --rm test
```

To run only the verified $100 transfer case:

```sh
docker compose --profile test run --build --rm test python -m unittest test.test_payments.PaymentTests.test_transfer_100_dollars_from_pinecrest_to_lopez -v
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

All five payment API tests passed in Docker on 2026-10-30: the $100 transfer,
insufficient funds for the combined batch, rollback of an earlier payee credit,
an unknown payer, and a payer deleted between lookup and update. The denial
tests assert the specific error code and verify that no payment changes persist.
The separate database tests cover migrations, model persistence, UUID uniqueness,
and payment foreign keys; those tests have not been run yet.

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
