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
Regression test: execute SQLite time-grain SQL from the engine spec against a
live database and assert on the empirically observed bucket boundaries.

Reference convention: ISO-8601 (week starts Monday).

Findings from live execution:
- WEEK grain buckets to Sunday (SQLite strftime('%w') convention, 0=Sunday).
  This is a dialect convention, not a defect.
- Redundant pairs (identical output across the full timestamp battery):
    THIRTY_MINUTES == HALF_HOUR
    WEEK == WEEK_STARTING_SUNDAY
    QUARTER == QUARTER_YEAR
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Generator
from datetime import datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# Timestamp battery: stresses Sunday/Monday boundary, month/quarter/year
# boundaries, leap day, and ordinary datetimes spanning two years.
# ---------------------------------------------------------------------------
TIMESTAMP_BATTERY: list[str] = [
    "2022-12-31 23:59:59",  # Saturday, last second of 2022
    "2023-01-01 00:00:00",  # Sunday, first second of 2023
    "2023-01-01 23:59:59",  # Sunday evening
    "2023-01-02 00:00:00",  # Monday
    "2023-01-02 00:00:01",  # Monday just after midnight
    "2023-03-31 23:59:59",  # Friday, last second of Q1
    "2023-04-01 00:00:00",  # Saturday, first second of Q2
    "2023-06-15 14:30:45",  # Thursday, ordinary
    "2023-06-30 23:59:59",  # Friday, last second of Q2
    "2023-07-01 00:00:00",  # Saturday, first second of Q3
    "2023-07-08 23:59:59",  # Saturday evening
    "2023-07-09 00:00:00",  # Sunday
    "2023-09-30 23:59:59",  # Saturday, last second of Q3
    "2023-10-01 00:00:00",  # Sunday, first second of Q4
    "2024-02-29 12:34:56",  # Thursday, leap day
    "2024-02-29 23:59:59",  # Thursday, last second of leap day
    "2024-03-01 00:00:00",  # Friday, day after leap day
    "2024-03-03 23:59:59",  # Sunday evening
    "2024-03-04 00:00:00",  # Monday
    "2024-11-20 08:15:30",  # Wednesday, ordinary
]

# ---------------------------------------------------------------------------
# Superset SQLite engine-spec SQL (verbatim from sqlite.py)
# ---------------------------------------------------------------------------
GRAIN_SQL: dict[str, str] = {
    "SECOND": "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:%S', {col}))",
    "FIVE_SECONDS": (
        "DATETIME({col}, printf('-%d seconds', CAST(strftime('%S', {col}) AS INT) % 5))"
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
    "WEEK": ("DATETIME({col}, 'start of day', -strftime('%w', {col}) || ' days')"),
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
        "DATETIME({col}, 'start of day', -strftime('%w', {col}) || ' days')"
    ),
    "WEEK_STARTING_MONDAY": (
        "DATETIME({col}, 'start of day', '-' || "
        "((strftime('%w', {col}) + 6) % 7) || ' days')"
    ),
}

# The 8 primary grains whose buckets are compared to ISO-8601.
PRIMARY_GRAINS = [
    "SECOND",
    "MINUTE",
    "HOUR",
    "DAY",
    "WEEK",
    "MONTH",
    "QUARTER",
    "YEAR",
]


# ---------------------------------------------------------------------------
# ISO-8601 reference implementations (week starts Monday)
# ---------------------------------------------------------------------------
_FMT = "%Y-%m-%d %H:%M:%S"


def _trunc_second(dt: datetime) -> str:
    return dt.strftime(_FMT)


def _trunc_five_seconds(dt: datetime) -> str:
    return dt.replace(second=dt.second - dt.second % 5).strftime(_FMT)


def _trunc_thirty_seconds(dt: datetime) -> str:
    return dt.replace(second=dt.second - dt.second % 30).strftime(_FMT)


def _trunc_minute(dt: datetime) -> str:
    return dt.replace(second=0).strftime(_FMT)


def _trunc_five_minutes(dt: datetime) -> str:
    return dt.replace(minute=dt.minute - dt.minute % 5, second=0).strftime(_FMT)


def _trunc_ten_minutes(dt: datetime) -> str:
    return dt.replace(minute=dt.minute - dt.minute % 10, second=0).strftime(_FMT)


def _trunc_fifteen_minutes(dt: datetime) -> str:
    return dt.replace(minute=dt.minute - dt.minute % 15, second=0).strftime(_FMT)


def _trunc_thirty_minutes(dt: datetime) -> str:
    return dt.replace(minute=dt.minute - dt.minute % 30, second=0).strftime(_FMT)


def _trunc_hour(dt: datetime) -> str:
    return dt.replace(minute=0, second=0).strftime(_FMT)


def _trunc_six_hours(dt: datetime) -> str:
    return dt.replace(hour=dt.hour - dt.hour % 6, minute=0, second=0).strftime(_FMT)


def _trunc_day(dt: datetime) -> str:
    return dt.replace(hour=0, minute=0, second=0).strftime(_FMT)


def _trunc_week_monday(dt: datetime) -> str:
    monday = dt - timedelta(days=dt.weekday())
    return monday.replace(hour=0, minute=0, second=0).strftime(_FMT)


def _trunc_week_sunday(dt: datetime) -> str:
    dow_sun = (dt.weekday() + 1) % 7  # 0=Sun
    sunday = dt - timedelta(days=dow_sun)
    return sunday.replace(hour=0, minute=0, second=0).strftime(_FMT)


def _trunc_week_ending_saturday(dt: datetime) -> str:
    days_to_sat = (5 - dt.weekday()) % 7
    sat = dt + timedelta(days=days_to_sat)
    return sat.replace(hour=0, minute=0, second=0).strftime(_FMT)


def _trunc_week_ending_sunday(dt: datetime) -> str:
    days_to_sun = (6 - dt.weekday()) % 7
    sun = dt + timedelta(days=days_to_sun)
    return sun.replace(hour=0, minute=0, second=0).strftime(_FMT)


def _trunc_month(dt: datetime) -> str:
    return dt.replace(day=1, hour=0, minute=0, second=0).strftime(_FMT)


def _trunc_quarter(dt: datetime) -> str:
    q_month = ((dt.month - 1) // 3) * 3 + 1
    return dt.replace(month=q_month, day=1, hour=0, minute=0, second=0).strftime(_FMT)


def _trunc_year(dt: datetime) -> str:
    return dt.replace(month=1, day=1, hour=0, minute=0, second=0).strftime(_FMT)


_ISO_DISPATCH: dict[str, Callable[[datetime], str]] = {
    "SECOND": _trunc_second,
    "FIVE_SECONDS": _trunc_five_seconds,
    "THIRTY_SECONDS": _trunc_thirty_seconds,
    "MINUTE": _trunc_minute,
    "FIVE_MINUTES": _trunc_five_minutes,
    "TEN_MINUTES": _trunc_ten_minutes,
    "FIFTEEN_MINUTES": _trunc_fifteen_minutes,
    "THIRTY_MINUTES": _trunc_thirty_minutes,
    "HALF_HOUR": _trunc_thirty_minutes,
    "HOUR": _trunc_hour,
    "SIX_HOURS": _trunc_six_hours,
    "DAY": _trunc_day,
    "WEEK": _trunc_week_monday,
    "WEEK_STARTING_MONDAY": _trunc_week_monday,
    "WEEK_STARTING_SUNDAY": _trunc_week_sunday,
    "WEEK_ENDING_SATURDAY": _trunc_week_ending_saturday,
    "WEEK_ENDING_SUNDAY": _trunc_week_ending_sunday,
    "MONTH": _trunc_month,
    "QUARTER": _trunc_quarter,
    "QUARTER_YEAR": _trunc_quarter,
    "YEAR": _trunc_year,
}


def _iso_bucket(grain: str, dt: datetime) -> str:
    """Compute the ISO-8601 bucket-start for *dt* at the given *grain*."""
    fn = _ISO_DISPATCH.get(grain)
    if fn is None:
        raise ValueError(f"Unknown grain: {grain}")
    return fn(dt)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def sqlite_conn() -> Generator[sqlite3.Connection]:
    """In-memory SQLite database populated with the timestamp battery."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ts_battery (ts TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO ts_battery (ts) VALUES (?)",
        [(ts,) for ts in TIMESTAMP_BATTERY],
    )
    conn.commit()
    yield conn
    conn.close()


def _execute_grain(conn: sqlite3.Connection, grain: str) -> list[tuple[str, str]]:
    """Execute a grain expression and return (input_ts, bucket) pairs."""
    expr = GRAIN_SQL[grain].format(col="ts")
    query = f"SELECT ts, {expr} AS bucket FROM ts_battery ORDER BY ts"  # noqa: S608
    rows = conn.execute(query).fetchall()
    return [(row[0], row[1]) for row in rows]


# ---------------------------------------------------------------------------
# Tests: each grain is executed live against SQLite and asserted.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("grain", PRIMARY_GRAINS)
def test_primary_grain_matches_observed_behavior(
    sqlite_conn: sqlite3.Connection, grain: str
) -> None:
    """
    Execute the engine-spec SQL for a primary grain against a live SQLite DB
    and assert the bucket matches the empirically observed convention.

    For WEEK, SQLite uses Sunday-start (strftime %w convention).
    All other primary grains match ISO-8601.
    """
    results = _execute_grain(sqlite_conn, grain)

    for ts_str, db_bucket in results:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        if grain == "WEEK":
            # SQLite WEEK starts on Sunday (dialect convention)
            dow_sun = (dt.weekday() + 1) % 7  # 0=Sun
            expected_sunday = dt - timedelta(days=dow_sun)
            expected = expected_sunday.replace(hour=0, minute=0, second=0).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        else:
            expected = _iso_bucket(grain, dt)
        assert db_bucket == expected, (
            f"grain={grain} ts={ts_str}: got {db_bucket!r}, expected {expected!r}"
        )


@pytest.mark.parametrize(
    "grain",
    [g for g in GRAIN_SQL if g not in PRIMARY_GRAINS],
)
def test_extended_grain_matches_observed_behavior(
    sqlite_conn: sqlite3.Connection, grain: str
) -> None:
    """
    Execute extended grain SQL live and assert against the empirically
    observed convention for each grain.
    """
    results = _execute_grain(sqlite_conn, grain)

    for ts_str, db_bucket in results:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        if grain == "WEEK_STARTING_SUNDAY":
            # Sunday-start (same as WEEK)
            dow_sun = (dt.weekday() + 1) % 7
            expected_sunday = dt - timedelta(days=dow_sun)
            expected = expected_sunday.replace(hour=0, minute=0, second=0).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        elif grain == "WEEK_STARTING_MONDAY":
            # Monday-start (matches ISO-8601)
            expected = _iso_bucket("WEEK_STARTING_MONDAY", dt)
        elif grain == "WEEK_ENDING_SATURDAY":
            expected = _iso_bucket("WEEK_ENDING_SATURDAY", dt)
        elif grain == "WEEK_ENDING_SUNDAY":
            expected = _iso_bucket("WEEK_ENDING_SUNDAY", dt)
        else:
            expected = _iso_bucket(grain, dt)
        assert db_bucket == expected, (
            f"grain={grain} ts={ts_str}: got {db_bucket!r}, expected {expected!r}"
        )


def test_week_diverges_from_iso8601_monday_start(
    sqlite_conn: sqlite3.Connection,
) -> None:
    """
    Explicitly verify that WEEK buckets to Sunday, diverging from ISO-8601
    Monday-start. This pins the known dialect convention.
    """
    results = _execute_grain(sqlite_conn, "WEEK")
    has_divergence = False

    for ts_str, db_bucket in results:
        dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
        iso_monday = _iso_bucket("WEEK", dt)
        if db_bucket != iso_monday:
            has_divergence = True
            # DB should bucket to a Sunday
            db_dt = datetime.strptime(db_bucket, "%Y-%m-%d %H:%M:%S")
            assert db_dt.weekday() == 6, (
                f"Expected Sunday bucket, got weekday={db_dt.weekday()}"
            )

    assert has_divergence, "Expected WEEK to diverge from ISO-8601 on some timestamps"


# ---------------------------------------------------------------------------
# Redundancy tests: execute BOTH expressions live and compare outputs.
# ---------------------------------------------------------------------------
def test_redundancy_thirty_minutes_equals_half_hour(
    sqlite_conn: sqlite3.Connection,
) -> None:
    """THIRTY_MINUTES and HALF_HOUR produce identical buckets (live execution)."""
    results_30m = _execute_grain(sqlite_conn, "THIRTY_MINUTES")
    results_hh = _execute_grain(sqlite_conn, "HALF_HOUR")
    assert [r[1] for r in results_30m] == [r[1] for r in results_hh]


def test_redundancy_week_equals_week_starting_sunday(
    sqlite_conn: sqlite3.Connection,
) -> None:
    """WEEK and WEEK_STARTING_SUNDAY produce identical buckets (live execution)."""
    results_w = _execute_grain(sqlite_conn, "WEEK")
    results_ws = _execute_grain(sqlite_conn, "WEEK_STARTING_SUNDAY")
    assert [r[1] for r in results_w] == [r[1] for r in results_ws]


def test_redundancy_quarter_equals_quarter_year(
    sqlite_conn: sqlite3.Connection,
) -> None:
    """QUARTER and QUARTER_YEAR produce identical buckets (live execution)."""
    results_q = _execute_grain(sqlite_conn, "QUARTER")
    results_qy = _execute_grain(sqlite_conn, "QUARTER_YEAR")
    assert [r[1] for r in results_q] == [r[1] for r in results_qy]
