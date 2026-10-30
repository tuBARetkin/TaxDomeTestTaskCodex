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
The API validates payment input; the service maps it and owns the transaction.
The repository updates firm balances in ascending ID order, then inserts payment
records. All 28 automated tests passed in Docker, using an isolated PostgreSQL
database for integration tests.
An optional stress runner sends concurrent, opposing payment batches through
Traefik and checks PostgreSQL's deadlock counter.

## Stack

Python 3.13, FastAPI, Uvicorn, SQLAlchemy, Alembic, Psycopg 3, PostgreSQL 17,
and Traefik 3.7.
Setuptools is the build dependency; tests use Python's built-in `unittest`.

## Run with Docker

Requires Docker with Docker Compose 2.23.1 or newer (included in Docker Desktop).
This version supports [inline configs](https://docs.docker.com/reference/compose-file/configs/),
used to embed Traefik's routing configuration in `compose.yaml`.

```sh
docker compose up --build
```

The default stack has exactly five containers, all configured in `compose.yaml`:

| Service | Role |
| --- | --- |
| `traefik` | HTTP load balancer, exposed on `localhost:8000` |
| `app` | First FastAPI instance; applies migrations before starting |
| `app-2` | Second FastAPI instance |
| `app-3` | Third FastAPI instance |
| `db` | One PostgreSQL 17 database shared by all three instances |

Startup waits for PostgreSQL, then starts `app` and applies Alembic migrations.
Once `app` is healthy, `app-2` and `app-3` start Uvicorn directly. This prevents
the three instances from running migrations concurrently on a fresh database.
Traefik starts after all three instances are healthy and distributes requests
using round robin (`strategy: wrr`, equal weight `1` for each instance). Its
backend health checks use `/health` to exclude unhealthy instances.

No local Python, PostgreSQL, or extra configuration files are required. The first
run downloads images and Python packages. The optional `test` profile retains
the separate test runner and test database. An optional `stress` profile adds a
load-generator container. These services are outside the five-container default
stack.

- API docs: http://localhost:8000/docs
- Database health check: http://localhost:8000/health

Both URLs go through Traefik; the app instances have no published host ports.
To use a different host port, run
`APP_PORT=8001 docker compose up --build`.

View the five services with `docker compose ps`. Traefik's JSON access logs include
the selected backend in `ServiceURL`:

```sh
docker compose logs -f traefik
```

After changing the inline routing configuration, recreate Traefik to load it:

```sh
docker compose up -d --no-deps --force-recreate traefik
```

Each app instance has its own SQLAlchemy connection pool: 5 retained connections
plus up to 10 temporary connections, for a maximum of 45 across the three app
instances. Traefik has no retry middleware configured; the idempotency limitation
below still applies.

Timeouts are configured in `compose.yaml`:

- PostgreSQL `transaction_timeout=13s` applies to both `db` and `db-test`.
  It terminates sessions whose transactions exceed 13 seconds, rolling back
  uncommitted changes. This server-wide setting also applies to migrations.
  See [PostgreSQL transaction timeouts](https://www.postgresql.org/docs/17/runtime-config-client.html#GUC-TRANSACTION-TIMEOUT).
- Traefik's HTTP entrypoint uses `writeTimeout=15s`, measured from the end of
  reading request headers through writing the response. This is not an
  application cancellation mechanism or a guarantee of a JSON timeout response.
  See [Traefik response timeouts](https://doc.traefik.io/traefik/routing/entrypoints/).

Apply these settings to an existing stack with `docker compose up -d db traefik`.

Fresh five-container startup and sequential payment routing were verified on
2026-10-30 using an isolated database volume. Nine payment requests were split
three per app instance, and the shared database balances and records were checked.

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
  strings, UUIDs, amount limits, batch size and total, and self-transfers.
  Each validated payment exposes its amount as integer cents.
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
- `payments` must contain between 1 and 1,000 entries.
- `amount` must be a positive string with zero, one, or two decimal places.
- Each amount and the batch total must fit within `2147483647` cents.
- Each payee must be different from the payer.
- Each payment requires a string `description`.

The API checks batch size before validating individual payment entries. All
input-only checks finish before the payment service is called or a database
connection is acquired. Dollar strings are converted to integer cents without
floating-point arithmetic. Invalid input returns `422` with the existing error
codes or FastAPI's standard field-validation error format. When a request breaks
multiple rules, the earlier validation stage determines the response.
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
`batch_amount_too_large`, `payer_not_found`, `payee_not_found`, and
`self_transfer_not_allowed`. Request-schema validation errors retain FastAPI's
standard `422` response format.

Insufficient balance returns `insufficient_funds`; a missing payer returns
`payer_not_found`. Both use HTTP `422` and roll back the entire batch. If the
payer's conditional update affects no rows, an additional existence query
distinguishes these cases, including a payer deleted after the initial lookup.

Transaction isolation is explicitly set before beginning the transaction in
`src/db/transaction.py`; change `PAYMENT_ISOLATION_LEVEL` there. The current
setting is `READ COMMITTED`. There is no `SELECT FOR UPDATE`; the ordered updates
take PostgreSQL's normal row locks. The ordering avoids reverse-order locking
between batches following this path, but is not a guarantee against deadlocks
involving other write paths. The stress runner below exercises concurrent requests;
a successful run cannot prove that every possible schedule is deadlock-free.

Before updating any balance, the repository checks that the delta dictionary's
firm IDs are in ascending order. An ordering bug raises `ValueError` before any
balance update executes, causing the transaction to roll back.

## Known limitations

- **No request idempotency.** The assignment's JSON request format is preserved
  and contains no client-supplied request or payment identifier. The endpoint
  implements no idempotency key or retry deduplication. If a batch commits but
  its HTTP response is delayed or lost, retrying the same payload can create
  duplicate payments and debit/credit the balances again if validation still
  passes. A client timeout does not imply that the original transaction rolled
  back. Database-generated payment IDs cannot identify a retried request, and
  identical payloads may also represent legitimate separate payments.
- **Self-transfers are not supported.** For otherwise valid input, if any
  payment's payee UUID matches the payer UUID, API validation rejects the entire
  batch with HTTP `422` and code `self_transfer_not_allowed` before calling the
  service. This applies whether the amount is below, equal to, or above the
  payer's balance. No payments or balance changes are saved, even when the batch
  also contains payments to other firms.
- **Single PostgreSQL database.** All firms and payments live in one PostgreSQL
  database, so each transfer can update both parties and insert payment records
  in one local transaction. Sharding firms across multiple databases and
  cross-shard transfers are outside the scope of this test task. Whether a real
  tax service needs sharding should be decided from measured workload and
  scaling requirements; this implementation does not assume it is necessary.
- **Maximum 1,000 payments per batch.** API validation rejects larger batches
  before validating or converting their entries, returning HTTP `422` with code
  `batch_too_large`. No payments or balance changes are saved. The limit is
  defined by `MAX_PAYMENTS_PER_BATCH` in `src/api/schemas.py`.
- **In-memory processing.** The request, service inputs, and insert records are
  held in memory. Aggregation visits every payment, and records are sorted before
  insertion. This implementation is intended for bounded batches, not millions
  of payments in one request. The API batch limit does not limit HTTP body bytes
  or prevent JSON parsing before schema validation; a request body size limit
  and streamed ingestion are not implemented.
- **32-bit INTEGER columns.** IDs, balances, and payment amounts use PostgreSQL
  `INTEGER`, whose range is `-2147483648` to `2147483647`. For money stored in
  cents, the maximum positive value is **$21,474,836.47**. Individual payments
  above this amount are rejected with `422`.
- **Batch totals.** Each payment can fit within INTEGER while their sum exceeds
  its maximum. Python's integer sum does not overflow, but API validation rejects
  totals above `2147483647` cents with `422` and code `batch_amount_too_large`
  before calling the service: a single firm's INTEGER balance cannot cover a
  larger batch.
- **Crediting a balance can overflow.** An individually valid payment and batch
  total do not guarantee that the recipient's existing balance plus its total
  credits fits INTEGER. For example, adding one cent to a balance of
  `2147483647` cents exceeds the limit. The SQL uses direct integer arithmetic,
  so this can raise a database overflow error. The error rolls back the whole transaction, but is not
  currently translated into `422` and can result in HTTP `500`. No wider-type
  casts or schema changes are implemented for this case.

## Migrations

Migrations run automatically when the `app` container starts. The other two app
instances skip migrations. To apply migrations manually:

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

## Code style

Ruff checks Python code and import order and applies consistent formatting.
Install the development tools and run the checks with:

```sh
python -m pip install -e '.[test,dev]'
ruff check .
ruff format --check .
```

To apply import fixes and formatting, run `ruff check --fix .` followed by
`ruff format .`.

## Structure

```text
src/
  api/           FastAPI entry point, routes, and request schemas
  services/      Mapping validated payments and transaction orchestration
  repositories/  Ordered balance updates and payment inserts in plain SQL
  db/            SQLAlchemy models and database infrastructure
test/            Database integration tests
migrations/      Alembic database migrations
compose.yaml     Traefik, three app instances, PostgreSQL, and optional test services
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

This builds the test runner with the optional HTTPX2 dependency and starts a
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

The eleven payment API tests cover the $100 transfer, insufficient funds for the
combined batch, rollback of an earlier payee credit, an unknown payer, a payer
deleted between lookup and update, rejection of self-transfers, and bulk batches.
The self-transfer cases cover amounts below, equal to, and above the balance, plus
a mixed batch containing a payment to another firm. The denial tests assert the
specific error code and verify that no payment changes persist.

The three bulk tests cover:

- Exactly 1,000 payments to 20 firms, including repeated recipients, different
  amounts with cents, and mixed request order. Expected balances and all stored
  payment details are checked; unrelated firms must remain unchanged.
- A batch with valid recipients and one missing recipient: `422 payee_not_found`
  with no saved payments or balance changes.
- 1,001 otherwise valid payments: `422 batch_too_large` with no saved payments
  or balance changes.

The nine validation tests cover malformed amounts, empty batches, invalid UUIDs,
individual and combined INTEGER boundaries, exact-balance transfers, and precise
dollar-to-cent conversion. Rejected requests must leave database state unchanged.

The four database tests cover migrations, model persistence, UUID uniqueness,
and payment foreign keys.
An additional unit test checks that unordered firm IDs are rejected before any
balance update executes. Three API tests verify that input-only rejections happen
before the service is called, that batch size is checked before individual items,
and that malformed fields retain FastAPI's standard error format. These tests
need no running database. All 28 tests passed in Docker on 2026-10-30.

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

## Concurrent payment stress test

The optional `stress` service uses the existing HTTPX2 test dependency. It sends
concurrent batches through Traefik to the three app instances, making overlapping
groups of firms pay each other in opposing directions. The expected outcome is
successful payments with no deadlocks.

Use a separate Compose project to keep the review database independent:

```sh
APP_PORT=8001 docker compose -p taxdome-stress up --build -d --wait
APP_PORT=8001 docker compose -p taxdome-stress --profile stress run --build --rm stress
```

Defaults: 1,000 requests, 24 concurrent clients, 8 firms, 3 payments per request,
and a 60-second HTTP client timeout. To change the workload:

```sh
APP_PORT=8001 docker compose -p taxdome-stress --profile stress run --build --rm stress --requests 2000 --concurrency 24 --firms 8 --batch-size 7
```

Each run creates its own funded firms with unique UUIDs and one-cent payments.
It leaves the seeded firms untouched and retains its rows for inspection under
the reported `run_id`. The runner does not retry failed requests.

The JSON report includes requests per second, p50/p95/p99 latency, HTTP statuses,
the increase in `pg_stat_database.deadlocks`, and checks of balances and payment
counts against successful responses. Exit code `0` means all requests returned
`201`, no new database deadlocks were reported, and the database checks matched;
otherwise it exits with `1`. HTTP errors alone are not classified as deadlocks.
A client timeout can leave an in-flight transaction, so a failed run's final
database state may still change afterward. Run without other traffic when using
the database-wide deadlock counter.

Verified locally on 2026-10-30 with the default workload above:

| Repository SQL | HTTP `201` responses | New PostgreSQL deadlocks | Runner exit code |
| --- | ---: | ---: | ---: |
| Original `ORDER BY id` | 1,000 / 1,000 | 0 | 0 |
| Only `ORDER BY id` temporarily removed | 545 / 1,000 | 317 | 1 |
| `ORDER BY id` restored | 1,000 / 1,000 | 0 | 0 |

All three app instances were rebuilt for each SQL change. The unsorted run also
returned `500` and `502` responses and had client timeouts; the deadlock count
came from PostgreSQL itself. Both ordered runs matched all expected balances and
3,000 payment records. The temporary SQL change was reverted. This demonstrates
that the workload detects the ordering regression, without guaranteeing that
every possible concurrent workload is deadlock-free.

These three runs preceded the addition of the ordering guard. With the guard,
unordered firm IDs are rejected before balance updates can acquire row locks.

Remove the isolated stress stack and its data afterward:

```sh
docker compose -p taxdome-stress --profile stress down --volumes
```
