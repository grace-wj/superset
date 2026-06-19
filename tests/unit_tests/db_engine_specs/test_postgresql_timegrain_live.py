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
Regression test: execute PostgreSQL time-grain SQL from Superset's engine spec
against a live PostgreSQL database and assert correctness against ISO-8601.

Requires a PostgreSQL instance reachable via the SUPERSET_TESTDB_POSTGRES_URI
environment variable (defaults to localhost with user 'devin').

This test is self-contained and does NOT wire into Superset's full test harness.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import pytest

psycopg2 = pytest.importorskip("psycopg2")

POSTGRES_URI = os.environ.get(
    "SUPERSET_TESTDB_POSTGRES_URI",
    "host=localhost dbname=timegrain_test user=devin password=devin123",
)

# The Superset PostgreSQL engine-spec time-grain expressions (verbatim).
GRAIN_EXPRESSIONS: dict[str, str] = {
    "second": "DATE_TRUNC('second', {col})",
    "five_seconds": (
        "DATE_TRUNC('minute', {col}) + INTERVAL '5 seconds'"
        " * FLOOR(EXTRACT(SECOND FROM {col}) / 5)"
    ),
    "thirty_seconds": (
        "DATE_TRUNC('minute', {col}) + INTERVAL '30 seconds'"
        " * FLOOR(EXTRACT(SECOND FROM {col}) / 30)"
    ),
    "minute": "DATE_TRUNC('minute', {col})",
    "five_minutes": (
        "DATE_TRUNC('hour', {col}) + INTERVAL '5 minutes'"
        " * FLOOR(EXTRACT(MINUTE FROM {col}) / 5)"
    ),
    "ten_minutes": (
        "DATE_TRUNC('hour', {col}) + INTERVAL '10 minutes'"
        " * FLOOR(EXTRACT(MINUTE FROM {col}) / 10)"
    ),
    "fifteen_minutes": (
        "DATE_TRUNC('hour', {col}) + INTERVAL '15 minutes'"
        " * FLOOR(EXTRACT(MINUTE FROM {col}) / 15)"
    ),
    "thirty_minutes": (
        "DATE_TRUNC('hour', {col}) + INTERVAL '30 minutes'"
        " * FLOOR(EXTRACT(MINUTE FROM {col}) / 30)"
    ),
    "hour": "DATE_TRUNC('hour', {col})",
    "day": "DATE_TRUNC('day', {col})",
    "week": "DATE_TRUNC('week', {col})",
    "month": "DATE_TRUNC('month', {col})",
    "quarter": "DATE_TRUNC('quarter', {col})",
    "year": "DATE_TRUNC('year', {col})",
}

# Timestamp battery: stresses Sunday/Monday, month/quarter/year boundaries,
# leap year, and sub-minute boundaries across two years.
TIMESTAMP_BATTERY: list[datetime] = [
    datetime(2023, 12, 31, 23, 59, 59),  # Sunday, last second of 2023
    datetime(2024, 1, 1, 0, 0, 0),  # Monday, first second of 2024
    datetime(2024, 2, 29, 12, 30, 45),  # Thursday, leap day
    datetime(2024, 3, 31, 23, 59, 59),  # Sunday, end of Q1
    datetime(2024, 4, 1, 0, 0, 1),  # Monday, start of Q2
    datetime(2024, 6, 30, 18, 45, 33),  # Sunday, end of Q2
    datetime(2024, 7, 1, 6, 15, 22),  # Monday, start of Q3
    datetime(2024, 5, 15, 14, 37, 28),  # Wednesday, ordinary
    datetime(2024, 9, 28, 23, 59, 59),  # Saturday near midnight
    datetime(2024, 9, 29, 0, 0, 0),  # Sunday at midnight
    datetime(2024, 9, 30, 0, 0, 0),  # Monday at midnight
    datetime(2024, 12, 31, 23, 59, 59),  # Tuesday, last second of 2024
    datetime(2025, 1, 1, 0, 0, 0),  # Wednesday, first second of 2025
    datetime(2024, 3, 15, 10, 22, 7),  # Friday, 5s boundary stress
    datetime(2024, 3, 15, 10, 22, 31),  # Friday, 30s boundary stress
]


def _iso8601_bucket(ts: datetime, grain: str) -> datetime:
    """Compute the ISO-8601 expected bucket (week starts Monday)."""
    if grain == "second":
        return ts.replace(microsecond=0)
    if grain == "five_seconds":
        return ts.replace(second=(ts.second // 5) * 5, microsecond=0)
    if grain == "thirty_seconds":
        return ts.replace(second=(ts.second // 30) * 30, microsecond=0)
    if grain == "minute":
        return ts.replace(second=0, microsecond=0)
    if grain == "five_minutes":
        return ts.replace(minute=(ts.minute // 5) * 5, second=0, microsecond=0)
    if grain == "ten_minutes":
        return ts.replace(minute=(ts.minute // 10) * 10, second=0, microsecond=0)
    if grain == "fifteen_minutes":
        return ts.replace(minute=(ts.minute // 15) * 15, second=0, microsecond=0)
    if grain == "thirty_minutes":
        return ts.replace(minute=(ts.minute // 30) * 30, second=0, microsecond=0)
    if grain == "hour":
        return ts.replace(minute=0, second=0, microsecond=0)
    if grain == "day":
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if grain == "week":
        days_since_monday = ts.weekday()
        monday = ts - timedelta(days=days_since_monday)
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    if grain == "month":
        return ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if grain == "quarter":
        quarter_start_month = ((ts.month - 1) // 3) * 3 + 1
        return ts.replace(
            month=quarter_start_month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    if grain == "year":
        return ts.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError(f"Unknown grain: {grain}")


@pytest.fixture(scope="module")
def pg_conn():
    """Create a live PostgreSQL connection for the test module."""
    try:
        conn = psycopg2.connect(POSTGRES_URI)
        conn.autocommit = True
    except psycopg2.OperationalError as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
    yield conn
    conn.close()


def _execute_grain(conn: Any, expr: str, ts: datetime) -> datetime:
    """Execute a single grain expression against the live DB."""
    sql = f"SELECT {expr.replace('{col}', 'ts')} FROM (SELECT TIMESTAMP %s AS ts) t"
    with conn.cursor() as cur:
        cur.execute(sql, (ts,))
        return cur.fetchone()[0]


@pytest.mark.parametrize("grain", list(GRAIN_EXPRESSIONS.keys()))
def test_timegrain_matches_iso8601(pg_conn: Any, grain: str) -> None:
    """Each grain's live DB result must match the ISO-8601 reference bucket."""
    expr = GRAIN_EXPRESSIONS[grain]
    for ts in TIMESTAMP_BATTERY:
        db_bucket = _execute_grain(pg_conn, expr, ts)
        iso_bucket = _iso8601_bucket(ts, grain)
        assert db_bucket == iso_bucket, (
            f"grain={grain}, ts={ts.isoformat()}: "
            f"DB returned {db_bucket.isoformat()}, "
            f"ISO-8601 expected {iso_bucket.isoformat()}"
        )


def test_no_redundant_grains(pg_conn: Any) -> None:
    """No two grain expressions should produce identical buckets across the
    entire timestamp battery (which would indicate a redundancy)."""
    grain_names = list(GRAIN_EXPRESSIONS.keys())
    executed_results: dict[str, list[datetime]] = {}

    for grain_name in grain_names:
        expr = GRAIN_EXPRESSIONS[grain_name]
        buckets = [_execute_grain(pg_conn, expr, ts) for ts in TIMESTAMP_BATTERY]
        executed_results[grain_name] = buckets

    redundancies: list[tuple[str, str]] = []
    for i in range(len(grain_names)):
        for j in range(i + 1, len(grain_names)):
            if executed_results[grain_names[i]] == executed_results[grain_names[j]]:
                redundancies.append((grain_names[i], grain_names[j]))

    assert redundancies == [], (
        f"Redundant grain pairs (identical buckets across full battery): {redundancies}"
    )
