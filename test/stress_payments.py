"""Send conflicting payment batches through the real HTTP load balancer."""

import argparse
import json
import math
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import httpx2
from sqlalchemy import create_engine, text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=1_000)
    parser.add_argument("--concurrency", type=int, default=24)
    parser.add_argument("--firms", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if not 1 <= args.requests <= 100_000:
        parser.error("requests must be between 1 and 100000")
    if not 1 <= args.concurrency <= min(args.requests, 128):
        parser.error("concurrency must be between 1 and min(requests, 128)")
    if not 2 <= args.firms <= 1_000:
        parser.error("firms must be between 2 and 1000")
    if not 1 <= args.batch_size <= 1_000:
        parser.error("batch-size must be between 1 and 1000")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be positive and finite")

    run_id = uuid4().hex
    # Every payment is one cent. Even the worst request ordering stays funded.
    starting_balance = args.requests * args.batch_size + 10_000
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        firms = []
        with engine.begin() as connection:
            for index in range(args.firms):
                firm_uuid = str(uuid4())
                firm_id = connection.execute(
                    text(
                        "INSERT INTO firms (name, balance_cents, uuid) "
                        "VALUES (:name, :balance, :uuid) RETURNING id"
                    ),
                    {
                        "name": f"Stress {run_id} {index}",
                        "balance": starting_balance,
                        "uuid": firm_uuid,
                    },
                ).scalar_one()
                firms.append((firm_id, firm_uuid))

        def database_stats():
            with engine.connect() as connection:
                return connection.execute(
                    text(
                        "SELECT deadlocks, stats_reset FROM pg_stat_database "
                        "WHERE datname = current_database()"
                    )
                ).one()

        before = database_stats()

        def payee_indexes(request_id):
            payer = request_id % args.firms
            direction = 1 if request_id % 2 == 0 else -1
            return [
                (payer + direction * (item % (args.firms - 1) + 1)) % args.firms
                for item in range(args.batch_size)
            ]

        barrier = Barrier(args.concurrency + 1)
        limits = httpx2.Limits(
            max_connections=args.concurrency, max_keepalive_connections=args.concurrency
        )
        with httpx2.Client(
            base_url=os.environ.get("STRESS_BASE_URL", "http://traefik"),
            timeout=args.timeout,
            limits=limits,
            trust_env=False,
        ) as client:

            def worker(worker_id):
                results = []
                barrier.wait()
                for request_id in range(worker_id, args.requests, args.concurrency):
                    body = {
                        "payer_firm_uuid": firms[request_id % args.firms][1],
                        "payments": [
                            {
                                "amount": "0.01",
                                "payee_firm_uuid": firms[payee][1],
                                "description": f"stress:{run_id}:{request_id}:{item}",
                            }
                            for item, payee in enumerate(payee_indexes(request_id))
                        ],
                    }
                    started = time.perf_counter()
                    try:
                        response = client.post("/api/v1/payments/", json=body)
                        status = str(response.status_code)
                        error = (
                            response.text[:300] if response.status_code != 201 else ""
                        )
                    except httpx2.HTTPError as exc:
                        status, error = "transport_error", str(exc)
                    results.append(
                        (request_id, status, time.perf_counter() - started, error)
                    )
                return results

            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                futures = [
                    executor.submit(worker, index) for index in range(args.concurrency)
                ]
                started = time.perf_counter()
                barrier.wait()
                results = [result for future in futures for result in future.result()]
                elapsed = time.perf_counter() - started

        # PostgreSQL cumulative statistics can lag behind completed transactions.
        time.sleep(1.1)
        after = database_stats()
        statuses = Counter(result[1] for result in results)
        latencies = sorted(result[2] * 1_000 for result in results)
        expected_balances = {firm_id: starting_balance for firm_id, _ in firms}
        for request_id, status, _, _ in results:
            if status == "201":
                expected_balances[firms[request_id % args.firms][0]] -= args.batch_size
                for payee in payee_indexes(request_id):
                    expected_balances[firms[payee][0]] += 1

        with engine.connect() as connection:
            balances = dict(
                connection.execute(
                    text("SELECT id, balance_cents FROM firms WHERE id = ANY(:ids)"),
                    {"ids": list(expected_balances)},
                ).all()
            )
            payment_count = connection.execute(
                text("SELECT COUNT(*) FROM payments WHERE payer_firm_id = ANY(:ids)"),
                {"ids": list(expected_balances)},
            ).scalar_one()

        deadlocks = after.deadlocks - before.deadlocks
        stats_valid = after.stats_reset == before.stats_reset and deadlocks >= 0
        balances_match = balances == expected_balances
        payments_match = payment_count == statuses["201"] * args.batch_size
        passed = (
            statuses["201"] == args.requests
            and stats_valid
            and deadlocks == 0
            and balances_match
            and payments_match
        )
        summary = {
            "passed": passed,
            "run_id": run_id,
            "requests": args.requests,
            "concurrency": args.concurrency,
            "firms": args.firms,
            "batch_size": args.batch_size,
            "seconds": round(elapsed, 3),
            "requests_per_second": round(args.requests / elapsed, 2),
            "latency_ms": {
                f"p{percentile}": round(
                    latencies[math.ceil(len(latencies) * percentile / 100) - 1], 2
                )
                for percentile in (50, 95, 99)
            },
            "http_statuses": dict(statuses),
            "database_deadlocks": deadlocks,
            "deadlock_counter_valid": stats_valid,
            "stored_payments": payment_count,
            "balances_match_successful_requests": balances_match,
            "payment_count_matches_successful_requests": payments_match,
            "first_errors": [
                {"request": request_id, "status": status, "detail": error}
                for request_id, status, _, error in results
                if status != "201"
            ][:5],
        }
        print(json.dumps(summary, indent=2), flush=True)
        return 0 if passed else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
