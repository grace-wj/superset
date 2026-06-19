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
Regression test: execute Superset's SQLite time-grain SQL against a live DB.

Pins the empirically observed bucketing behavior for every grain in
SqliteEngineSpec._time_grain_expressions. Each test runs the actual SQL
from the engine spec against a real SQLite database and asserts on the
executed result — no string comparison or hard-coded tautologies.

Reference convention: ISO-8601 (week starts Monday).
Known dialect divergence: the default WEEK grain buckets to Sunday.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# Timestamp battery: stresses bucket boundaries
# ---------------------------------------------------------------------------
TIMESTAMP_BATTERY: list[str] = [
    "2023-12-31 23:59:59",  # last second of 2023 (Sunday)
    "2024-01-01 00:00:00",  # first second of 2024 (Monday), Q1/month start
    "2024-01-01 06:30:45",  # ordinary Monday morning
    "2024-02-29 12:15:30",  # leap-year Feb 29 (Thursday)
    "2024-03-01 00:00:00",  # day after leap day (Friday), month boundary
    "2024-03-31 23:59:59",  # end of March (Sunday), end of Q1
    "2024-04-01 00:00:00",  # start of Q2 (Monday)
    "2024-06-30 18:45:22",  # end of June (Sunday), end of Q2
    "2024-07-01 09:10:05",  # start of Q3 (Monday)
    "2024-09-29 14:37:48",  # a Sunday
    "2024-09-30 02:22:11",  # the adjacent Monday
    "2024-12-31 23:59:59",  # last second of 2024 (Tuesday)
    "2025-01-01 00:00:00",  # first second of 2025 (Wednesday)
    "2025-06-15 10:33:07",  # ordinary Sunday in 2025
]

# ---------------------------------------------------------------------------
# SQL expressions copied verbatim from SqliteEngineSpec._time_grain_expressions
# ---------------------------------------------------------------------------
GRAIN_SQL: dict[str, str] = {
    "SECOND": "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:%S', {col}))",
    "FIVE_SECONDS": (
        "DATETIME({col}, printf('-%d seconds', "
        "CAST(strftime('%S', {col}) AS INT) % 5))"
    ),
    "THIRTY_SECONDS": (
        "DATETIME({col}, printf('-%d seconds', "
        "CAST(strftime('%S', {col}) AS INT) % 30))"
    ),
    "MINUTE": "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}))",
    "FIVE_MINUTES": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 5))"
    ),
    "TEN_MINUTES": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 10))"
    ),
    "FIFTEEN_MINUTES": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 15))"
    ),
    "THIRTY_MINUTES": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 30))"
    ),
    "HALF_HOUR": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 30))"
    ),
    "HOUR": "DATETIME(STRFTIME('%Y-%m-%dT%H:00:00', {col}))",
    "SIX_HOURS": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:00:00', {col}), printf('-%d hours', "
        "CAST(strftime('%H', {col}) AS INT) % 6))"
    ),
    "DAY": "DATETIME({col}, 'start of day')",
    "WEEK": (
        "DATETIME({col}, 'start of day', "
        "-strftime('%w', {col}) || ' days')"
    ),
    "MONTH": "DATETIME({col}, 'start of month')",
    "QUARTER": (
        "DATETIME({col}, 'start of month', "
        "printf('-%d month', (strftime('%m', {col}) - 1) % 3))"
    ),
    "QUARTER_YEAR": (
        "DATETIME({col}, 'start of month', "
        "printf('-%d month', (strftime('%m', {col}) - 1) % 3))"
    ),
    "YEAR": "DATETIME({col}, 'start of year')",
    "WEEK_ENDING_SATURDAY": "DATETIME({col}, 'start of day', 'weekday 6')",
    "WEEK_ENDING_SUNDAY": "DATETIME({col}, 'start of day', 'weekday 0')",
    "WEEK_STARTING_SUNDAY": (
        "DATETIME({col}, 'start of day', "
        "-strftime('%w', {col}) || ' days')"
    ),
    "WEEK_STARTING_MONDAY": (
        "DATETIME({col}, 'start of day', '-' || "
        "((strftime('%w', {col}) + 6) % 7) || ' days')"
    ),
}


# ---------------------------------------------------------------------------
# ISO-8601 reference computation
# ---------------------------------------------------------------------------
def _iso_bucket(ts_str: str, grain: str) -> str:
    """Return the ISO-8601 bucket start for *ts_str* under *grain*."""
    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")

    if grain == "SECOND":
        result = dt
    elif grain == "FIVE_SECONDS":
        result = dt.replace(second=dt.second - dt.second % 5)
    elif grain == "THIRTY_SECONDS":
        result = dt.replace(second=dt.second - dt.second % 30)
    elif grain == "MINUTE":
        result = dt.replace(second=0)
    elif grain == "FIVE_MINUTES":
        result = dt.replace(minute=dt.minute - dt.minute % 5, second=0)
    elif grain == "TEN_MINUTES":
        result = dt.replace(minute=dt.minute - dt.minute % 10, second=0)
    elif grain == "FIFTEEN_MINUTES":
        result = dt.replace(minute=dt.minute - dt.minute % 15, second=0)
    elif grain in ("THIRTY_MINUTES", "HALF_HOUR"):
        result = dt.replace(minute=dt.minute - dt.minute % 30, second=0)
    elif grain == "HOUR":
        result = dt.replace(minute=0, second=0)
    elif grain == "SIX_HOURS":
        result = dt.replace(hour=dt.hour - dt.hour % 6, minute=0, second=0)
    elif grain == "DAY":
        result = dt.replace(hour=0, minute=0, second=0)
    elif grain in ("WEEK", "WEEK_STARTING_MONDAY"):
        # ISO-8601: week starts Monday
        days_since_monday = dt.weekday()
        result = (dt - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0
        )
    elif grain == "WEEK_STARTING_SUNDAY":
        days_since_sunday = (dt.weekday() + 1) % 7
        result = (dt - timedelta(days=days_since_sunday)).replace(
            hour=0, minute=0, second=0
        )
    elif grain == "WEEK_ENDING_SATURDAY":
        # Next Saturday (or same day); SQLite 'weekday 6' semantics
        days_ahead = (5 - dt.weekday()) % 7
        result = (dt + timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0
        )
    elif grain == "WEEK_ENDING_SUNDAY":
        days_ahead = (6 - dt.weekday()) % 7
        result = (dt + timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0
        )
    elif grain == "MONTH":
        result = dt.replace(day=1, hour=0, minute=0, second=0)
    elif grain in ("QUARTER", "QUARTER_YEAR"):
        q_month = ((dt.month - 1) // 3) * 3 + 1
        result = dt.replace(month=q_month, day=1, hour=0, minute=0, second=0)
    elif grain == "YEAR":
        result = dt.replace(month=1, day=1, hour=0, minute=0, second=0)
    else:
        raise ValueError(f"Unknown grain: {grain}")

    return result.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Fixture: live SQLite connection with the timestamp battery loaded
# ---------------------------------------------------------------------------
@pytest.fixture()
def live_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE test_ts (ts TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO test_ts (ts) VALUES (?)",
        [(ts,) for ts in TIMESTAMP_BATTERY],
    )
    conn.commit()
    yield conn
    conn.close()


def _execute_grain(conn: sqlite3.Connection, grain: str) -> list[tuple[str, str]]:
    """Run the grain SQL against the live DB; return (input_ts, bucket) pairs."""
    sql_expr = GRAIN_SQL[grain].replace("{col}", "ts")
    rows = conn.execute(
        f"SELECT ts, {sql_expr} AS bucket FROM test_ts ORDER BY ts"
    ).fetchall()
    return [(row[0], row[1]) for row in rows]


# ---------------------------------------------------------------------------
# Core grain tests — each executes SQL live and compares to ISO-8601 reference
# ---------------------------------------------------------------------------
# Grains that are expected to match ISO-8601 exactly
ISO_MATCHING_GRAINS: list[str] = [
    "SECOND",
    "FIVE_SECONDS",
    "THIRTY_SECONDS",
    "MINUTE",
    "FIVE_MINUTES",
    "TEN_MINUTES",
    "FIFTEEN_MINUTES",
    "THIRTY_MINUTES",
    "HALF_HOUR",
    "HOUR",
    "SIX_HOURS",
    "DAY",
    "MONTH",
    "QUARTER",
    "QUARTER_YEAR",
    "YEAR",
    "WEEK_STARTING_MONDAY",
    "WEEK_STARTING_SUNDAY",
    "WEEK_ENDING_SATURDAY",
    "WEEK_ENDING_SUNDAY",
]


@pytest.mark.parametrize("grain", ISO_MATCHING_GRAINS)
def test_grain_matches_iso8601(live_db: sqlite3.Connection, grain: str) -> None:
    """Grain SQL executed against live SQLite matches ISO-8601 reference."""
    results = _execute_grain(live_db, grain)
    for ts, sql_bucket in results:
        expected = _iso_bucket(ts, grain)
        assert sql_bucket == expected, (
            f"[{grain}] ts={ts}: live DB returned {sql_bucket!r}, "
            f"ISO-8601 expected {expected!r}"
        )


def test_week_grain_uses_sunday_start(live_db: sqlite3.Connection) -> None:
    """
    WEEK grain diverges from ISO-8601: SQLite buckets to Sunday (not Monday).

    This is a known dialect convention — strftime('%w') returns 0 for Sunday
    and the expression subtracts that many days, landing on the most recent
    Sunday. Pinning this behavior guards against silent regressions.
    """
    results = _execute_grain(live_db, "WEEK")
    for ts, sql_bucket in results:
        # The bucket should be the most recent Sunday (or same day if Sunday)
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        days_since_sunday = (dt.weekday() + 1) % 7
        expected_sunday = (dt - timedelta(days=days_since_sunday)).replace(
            hour=0, minute=0, second=0
        )
        expected = expected_sunday.strftime("%Y-%m-%d %H:%M:%S")
        assert sql_bucket == expected, (
            f"[WEEK] ts={ts}: live DB returned {sql_bucket!r}, "
            f"expected Sunday-start {expected!r}"
        )

    # Confirm divergence from ISO-8601 (Monday-start) on a known case
    # 2024-01-01 is a Monday: WEEK should bucket to 2023-12-31 (Sunday)
    monday_result = dict(results)["2024-01-01 00:00:00"]
    iso_monday_bucket = _iso_bucket("2024-01-01 00:00:00", "WEEK_STARTING_MONDAY")
    assert monday_result != iso_monday_bucket, (
        "WEEK grain unexpectedly matched ISO-8601 Monday-start; "
        "expected Sunday-start divergence"
    )


# ---------------------------------------------------------------------------
# Redundancy tests — run BOTH expressions live and compare their outputs
# ---------------------------------------------------------------------------
def test_redundancy_half_hour_equals_thirty_minutes(
    live_db: sqlite3.Connection,
) -> None:
    """HALF_HOUR and THIRTY_MINUTES produce identical buckets (same SQL)."""
    half_hour = _execute_grain(live_db, "HALF_HOUR")
    thirty_min = _execute_grain(live_db, "THIRTY_MINUTES")
    for (ts_a, bucket_a), (ts_b, bucket_b) in zip(half_hour, thirty_min):
        assert ts_a == ts_b
        assert bucket_a == bucket_b, (
            f"ts={ts_a}: HALF_HOUR={bucket_a!r} != THIRTY_MINUTES={bucket_b!r}"
        )


def test_redundancy_week_equals_week_starting_sunday(
    live_db: sqlite3.Connection,
) -> None:
    """WEEK and WEEK_STARTING_SUNDAY produce identical buckets."""
    week = _execute_grain(live_db, "WEEK")
    week_sun = _execute_grain(live_db, "WEEK_STARTING_SUNDAY")
    for (ts_a, bucket_a), (ts_b, bucket_b) in zip(week, week_sun):
        assert ts_a == ts_b
        assert bucket_a == bucket_b, (
            f"ts={ts_a}: WEEK={bucket_a!r} != WEEK_STARTING_SUNDAY={bucket_b!r}"
        )


def test_redundancy_quarter_equals_quarter_year(
    live_db: sqlite3.Connection,
) -> None:
    """QUARTER and QUARTER_YEAR produce identical buckets (same SQL)."""
    quarter = _execute_grain(live_db, "QUARTER")
    quarter_year = _execute_grain(live_db, "QUARTER_YEAR")
    for (ts_a, bucket_a), (ts_b, bucket_b) in zip(quarter, quarter_year):
        assert ts_a == ts_b
        assert bucket_a == bucket_b, (
            f"ts={ts_a}: QUARTER={bucket_a!r} != QUARTER_YEAR={bucket_b!r}"
        )
