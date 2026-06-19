# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
"""
Regression test: verify PostgreSQL time-grain SQL from Superset's engine spec
against a live PostgreSQL database, compared to ISO-8601 reference buckets.

Requires a running PostgreSQL instance. Skipped automatically if unavailable.
Run standalone:  pytest tests/unit_tests/db_engine_specs/test_postgres_time_grain_live.py -v
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

try:
    import psycopg2
except ImportError:
    psycopg2 = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Time-grain SQL expressions — copied verbatim from
# superset/db_engine_specs/postgres.py  PostgresBaseEngineSpec._time_grain_expressions
# ---------------------------------------------------------------------------
GRAIN_EXPRESSIONS: dict[str, str] = {
    "SECOND": "DATE_TRUNC('second', {col})",
    "FIVE_SECONDS": (
        "DATE_TRUNC('minute', {col}) "
        "+ INTERVAL '5 seconds' * FLOOR(EXTRACT(SECOND FROM {col}) / 5)"
    ),
    "THIRTY_SECONDS": (
        "DATE_TRUNC('minute', {col}) "
        "+ INTERVAL '30 seconds' * FLOOR(EXTRACT(SECOND FROM {col}) / 30)"
    ),
    "MINUTE": "DATE_TRUNC('minute', {col})",
    "FIVE_MINUTES": (
        "DATE_TRUNC('hour', {col}) "
        "+ INTERVAL '5 minutes' * FLOOR(EXTRACT(MINUTE FROM {col}) / 5)"
    ),
    "TEN_MINUTES": (
        "DATE_TRUNC('hour', {col}) "
        "+ INTERVAL '10 minutes' * FLOOR(EXTRACT(MINUTE FROM {col}) / 10)"
    ),
    "FIFTEEN_MINUTES": (
        "DATE_TRUNC('hour', {col}) "
        "+ INTERVAL '15 minutes' * FLOOR(EXTRACT(MINUTE FROM {col}) / 15)"
    ),
    "THIRTY_MINUTES": (
        "DATE_TRUNC('hour', {col}) "
        "+ INTERVAL '30 minutes' * FLOOR(EXTRACT(MINUTE FROM {col}) / 30)"
    ),
    "HOUR": "DATE_TRUNC('hour', {col})",
    "DAY": "DATE_TRUNC('day', {col})",
    "WEEK": "DATE_TRUNC('week', {col})",
    "MONTH": "DATE_TRUNC('month', {col})",
    "QUARTER": "DATE_TRUNC('quarter', {col})",
    "YEAR": "DATE_TRUNC('year', {col})",
}

# ---------------------------------------------------------------------------
# Timestamp battery — stresses bucket boundaries
# ---------------------------------------------------------------------------
TIMESTAMPS: list[datetime] = [
    datetime(2023, 12, 31, 23, 59, 58),  # last-second-of-2023, Sunday
    datetime(2024, 1, 1, 0, 0, 0),  # new-year 2024, Monday
    datetime(2024, 2, 29, 12, 30, 45),  # leap day, Thursday
    datetime(2024, 3, 1, 0, 0, 0),  # day after leap day, Friday
    datetime(2024, 3, 31, 23, 59, 59),  # end of March / Q1, Sunday
    datetime(2024, 4, 1, 0, 0, 1),  # start of April / Q2, Monday
    datetime(2024, 6, 30, 23, 59, 59),  # end of June / Q2, Sunday
    datetime(2024, 7, 1, 0, 0, 0),  # start of July / Q3, Monday
    datetime(2024, 9, 30, 23, 59, 59),  # end of September / Q3, Monday
    datetime(2024, 10, 1, 0, 0, 0),  # start of October / Q4, Tuesday
    datetime(2024, 7, 14, 15, 23, 47),  # ordinary Sunday
    datetime(2024, 7, 15, 8, 17, 33),  # ordinary Monday
    datetime(2025, 3, 15, 10, 45, 22),  # mid-2025, Saturday
]


# ---------------------------------------------------------------------------
# ISO-8601 reference computation (week starts Monday)
# ---------------------------------------------------------------------------
def _iso8601_bucket(grain: str, ts: datetime) -> datetime:
    if grain == "SECOND":
        return ts.replace(microsecond=0)
    if grain == "FIVE_SECONDS":
        return ts.replace(second=(ts.second // 5) * 5, microsecond=0)
    if grain == "THIRTY_SECONDS":
        return ts.replace(second=(ts.second // 30) * 30, microsecond=0)
    if grain == "MINUTE":
        return ts.replace(second=0, microsecond=0)
    if grain == "FIVE_MINUTES":
        return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)
    if grain == "TEN_MINUTES":
        return ts.replace(minute=(ts.minute // 10) * 10, second=0, microsecond=0)
    if grain == "FIFTEEN_MINUTES":
        return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
    if grain == "THIRTY_MINUTES":
        return ts.replace(minute=(ts.minute // 30) * 30, second=0, microsecond=0)
    if grain == "HOUR":
        return ts.replace(minute=0, second=0, microsecond=0)
    if grain == "DAY":
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if grain == "WEEK":
        monday = ts - timedelta(days=ts.isoweekday() - 1)
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    if grain == "MONTH":
        return ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if grain == "QUARTER":
        q_month = ((ts.month - 1) // 3) * 3 + 1
        return ts.replace(month=q_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    if grain == "YEAR":
        return ts.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    raise ValueError(f"Unknown grain: {grain}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_PG_DSN = "dbname=superset_test user=superset_tester password=test123 host=localhost"


def _pg_available() -> bool:
    if psycopg2 is None:
        return False
    try:
        conn = psycopg2.connect(_PG_DSN)
        conn.close()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _pg_available(),
    reason="Live PostgreSQL not available — skipping live time-grain tests",
)


@pytest.fixture(scope="module")
def pg_conn():
    conn = psycopg2.connect(_PG_DSN)
    conn.autocommit = True
    yield conn
    conn.close()


def _execute_grain(cur, grain_name: str, ts: datetime) -> datetime:
    """Run the engine-spec SQL for *grain_name* against *ts* and return the bucket."""
    sql_template = GRAIN_EXPRESSIONS[grain_name]
    ts_literal = ts.strftime("%Y-%m-%d %H:%M:%S")
    sql_expr = sql_template.replace("{col}", f"TIMESTAMP '{ts_literal}'")
    cur.execute(f"SELECT {sql_expr}")
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Tests — each executes engine-spec SQL against a live PostgreSQL instance
# ---------------------------------------------------------------------------
@requires_postgres
@pytest.mark.parametrize("grain", list(GRAIN_EXPRESSIONS))
def test_grain_matches_iso8601(pg_conn, grain: str) -> None:
    """Every grain bucket returned by PostgreSQL must match the ISO-8601 reference."""
    cur = pg_conn.cursor()
    for ts in TIMESTAMPS:
        db_bucket = _execute_grain(cur, grain, ts)
        expected = _iso8601_bucket(grain, ts)
        assert db_bucket == expected, (
            f"grain={grain}  ts={ts}  db={db_bucket}  iso8601={expected}"
        )
    cur.close()


@requires_postgres
def test_no_redundant_grains(pg_conn) -> None:
    """No two distinct grain expressions should produce identical buckets
    across the entire timestamp battery when executed against the live DB."""
    cur = pg_conn.cursor()
    bucket_vectors: dict[str, list[datetime]] = {}
    for grain in GRAIN_EXPRESSIONS:
        bucket_vectors[grain] = [
            _execute_grain(cur, grain, ts) for ts in TIMESTAMPS
        ]
    cur.close()

    names = list(bucket_vectors)
    redundant_pairs: list[tuple[str, str]] = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if bucket_vectors[names[i]] == bucket_vectors[names[j]]:
                redundant_pairs.append((names[i], names[j]))

    assert redundant_pairs == [], (
        f"Redundant grain pairs (identical live output): {redundant_pairs}"
    )
