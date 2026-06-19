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
Regression tests for PostgreSQL time-grain SQL expressions executed against a
live database.

These tests verify that every ``_time_grain_expressions`` entry in
``PostgresBaseEngineSpec`` produces correct period-start buckets when run on a
real PostgreSQL instance. The reference convention is **ISO-8601** (week starts
Monday) applied identically to every engine so that dialect-specific
conventions surface as explicit, reviewable discrepancies rather than silent
assumptions.

Requirements
------------
* A running PostgreSQL instance reachable at ``localhost:5432``
  with user ``devin`` / password ``devin`` and database ``devin_test``.
* ``psycopg2`` (or ``psycopg2-binary``) installed.

Run with::

    pytest tests/unit_tests/db_engine_specs/test_postgres_time_grain_live.py -v

The tests are skipped automatically when the database is unreachable.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

try:
    import psycopg2

    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

# ---------------------------------------------------------------------------
# Superset's PostgreSQL time-grain SQL (from postgres.py)
# ---------------------------------------------------------------------------
GRAIN_SQL: dict[str, str] = {
    "SECOND": "DATE_TRUNC('second', {col})",
    "FIVE_SECONDS": (
        "DATE_TRUNC('minute', {col}) + INTERVAL '5 seconds'"
        " * FLOOR(EXTRACT(SECOND FROM {col}) / 5)"
    ),
    "THIRTY_SECONDS": (
        "DATE_TRUNC('minute', {col}) + INTERVAL '30 seconds'"
        " * FLOOR(EXTRACT(SECOND FROM {col}) / 30)"
    ),
    "MINUTE": "DATE_TRUNC('minute', {col})",
    "FIVE_MINUTES": (
        "DATE_TRUNC('hour', {col}) + INTERVAL '5 minutes'"
        " * FLOOR(EXTRACT(MINUTE FROM {col}) / 5)"
    ),
    "TEN_MINUTES": (
        "DATE_TRUNC('hour', {col}) + INTERVAL '10 minutes'"
        " * FLOOR(EXTRACT(MINUTE FROM {col}) / 10)"
    ),
    "FIFTEEN_MINUTES": (
        "DATE_TRUNC('hour', {col}) + INTERVAL '15 minutes'"
        " * FLOOR(EXTRACT(MINUTE FROM {col}) / 15)"
    ),
    "THIRTY_MINUTES": (
        "DATE_TRUNC('hour', {col}) + INTERVAL '30 minutes'"
        " * FLOOR(EXTRACT(MINUTE FROM {col}) / 30)"
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
    # Sunday -> Monday year boundary
    datetime(2023, 12, 31, 23, 59, 59),  # Sunday, last second of 2023
    datetime(2024, 1, 1, 0, 0, 1),  # Monday, first second of 2024
    # Leap day
    datetime(2024, 2, 29, 12, 30, 45),  # Thursday, leap day
    # Month / Q1->Q2 boundary
    datetime(2024, 3, 31, 23, 59, 59),  # Sunday, last second of March
    datetime(2024, 4, 1, 0, 0, 1),  # Monday, first second of April
    # Q2->Q3 boundary
    datetime(2024, 6, 30, 23, 59, 59),  # Sunday, last second of June
    datetime(2024, 7, 1, 0, 0, 1),  # Monday, first second of July
    # Q3->Q4 boundary
    datetime(2024, 9, 30, 23, 59, 59),  # Monday, last second of September
    datetime(2024, 10, 1, 0, 0, 1),  # Tuesday, first second of October
    # Year-end
    datetime(2024, 12, 31, 23, 59, 59),  # Tuesday, last second of 2024
    # Ordinary mid-week (different year)
    datetime(2023, 6, 15, 14, 23, 37),  # Thursday
    datetime(2023, 8, 19, 7, 47, 12),  # Saturday
    # Midnight exactly
    datetime(2024, 5, 13, 0, 0, 0),  # Monday midnight
    # Sub-minute boundaries (second 29 vs 30)
    datetime(2024, 3, 15, 10, 17, 29),  # 5s->25, 30s->0
    datetime(2024, 3, 15, 10, 17, 30),  # 5s->30, 30s->30
]


# ---------------------------------------------------------------------------
# ISO-8601 reference computation
# ---------------------------------------------------------------------------
def _trunc_sub_minute(grain: str, ts: datetime) -> datetime | None:
    """Handle sub-minute grains; return None if *grain* is not sub-minute."""
    mapping: dict[str, int] = {
        "SECOND": 0,
        "FIVE_SECONDS": 5,
        "THIRTY_SECONDS": 30,
    }
    if grain == "SECOND":
        return ts.replace(microsecond=0)
    if grain in mapping:
        step = mapping[grain]
        return ts.replace(second=(ts.second // step) * step, microsecond=0)
    if grain == "MINUTE":
        return ts.replace(second=0, microsecond=0)
    return None


def _trunc_sub_hour(grain: str, ts: datetime) -> datetime | None:
    """Handle sub-hour grains (5/10/15/30 min); return None otherwise."""
    mapping: dict[str, int] = {
        "FIVE_MINUTES": 5,
        "TEN_MINUTES": 10,
        "FIFTEEN_MINUTES": 15,
        "THIRTY_MINUTES": 30,
    }
    if (step := mapping.get(grain)) is not None:
        return ts.replace(minute=(ts.minute // step) * step, second=0, microsecond=0)
    if grain == "HOUR":
        return ts.replace(minute=0, second=0, microsecond=0)
    return None


def _trunc_calendar(grain: str, ts: datetime) -> datetime:
    """Handle day / week / month / quarter / year grains."""
    midnight = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if grain == "DAY":
        return midnight
    if grain == "WEEK":
        return midnight - timedelta(days=ts.weekday())
    if grain == "MONTH":
        return midnight.replace(day=1)
    if grain == "QUARTER":
        q_month = ((ts.month - 1) // 3) * 3 + 1
        return midnight.replace(month=q_month, day=1)
    if grain == "YEAR":
        return midnight.replace(month=1, day=1)
    raise ValueError(f"Unknown grain: {grain}")


def _iso_bucket(grain: str, ts: datetime) -> datetime:
    """Compute the expected period-start bucket under ISO-8601."""
    result = _trunc_sub_minute(grain, ts)
    if result is not None:
        return result
    result = _trunc_sub_hour(grain, ts)
    if result is not None:
        return result
    return _trunc_calendar(grain, ts)


# ---------------------------------------------------------------------------
# Fixture: live PostgreSQL connection
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pg_conn():  # noqa: ANN201
    if not _HAS_PSYCOPG2:
        pytest.skip("psycopg2 not installed")
    try:
        conn = psycopg2.connect(
            host="localhost",
            port=5432,
            dbname="devin_test",
            user="devin",
            password="devin",  # noqa: S106
            connect_timeout=5,
        )
        conn.autocommit = True
    except Exception:
        pytest.skip("PostgreSQL not reachable at localhost:5432")
    yield conn
    conn.close()


def _run_grain_sql(conn: Any, grain: str, ts: datetime) -> datetime:
    """Execute the engine-spec SQL for *grain* on *ts* and return the bucket."""
    ts_literal = ts.strftime("%Y-%m-%d %H:%M:%S")
    sql_expr = GRAIN_SQL[grain].replace("{col}", f"TIMESTAMP '{ts_literal}'")
    with conn.cursor() as cur:
        cur.execute(f"SELECT {sql_expr};")
        row = cur.fetchone()
        assert row is not None
        return row[0]


# ---------------------------------------------------------------------------
# Per-grain tests: execute SQL live and compare to ISO-8601
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("grain", list(GRAIN_SQL.keys()))
def test_grain_matches_iso8601(
    pg_conn: Any,
    grain: str,
) -> None:
    """Every timestamp in the battery must bucket identically via live SQL
    and the ISO-8601 Python reference."""
    mismatches: list[str] = []
    for ts in TIMESTAMPS:
        db_bucket = _run_grain_sql(pg_conn, grain, ts)
        iso_bucket = _iso_bucket(grain, ts)
        if db_bucket != iso_bucket:
            mismatches.append(f"  ts={ts}  db={db_bucket}  iso={iso_bucket}")
    assert not mismatches, (
        f"Grain {grain} diverged from ISO-8601 on {len(mismatches)} "
        f"timestamp(s):\n" + "\n".join(mismatches)
    )


# ---------------------------------------------------------------------------
# Redundancy test: ensure no two grains produce identical buckets
# ---------------------------------------------------------------------------
def test_no_redundant_grain_pairs(pg_conn: Any) -> None:
    """No two grain expressions should produce identical bucket sequences
    across the entire timestamp battery when executed against a live DB."""
    grain_names = list(GRAIN_SQL.keys())
    # Collect live-executed buckets per grain
    buckets: dict[str, list[datetime]] = {}
    for grain in grain_names:
        buckets[grain] = [_run_grain_sql(pg_conn, grain, ts) for ts in TIMESTAMPS]

    redundant: list[str] = []
    for i, ga in enumerate(grain_names):
        for gb in grain_names[i + 1 :]:
            if buckets[ga] == buckets[gb]:
                redundant.append(f"{ga} == {gb}")

    assert not redundant, (
        "Redundant grain pairs (identical buckets across entire battery): "
        + ", ".join(redundant)
    )
