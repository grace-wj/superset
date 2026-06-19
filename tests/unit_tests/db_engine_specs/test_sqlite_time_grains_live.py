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
Regression test: verify SQLite time-grain SQL expressions against a live DB.

Executes every time-grain expression from SqliteEngineSpec._time_grain_expressions
against a real SQLite database and asserts on the empirically observed buckets.
Reference convention: ISO-8601 (week starts Monday).

Discrepancy surfaced:
  - WEEK grain uses Sunday-start (SQLite %w convention), not ISO-8601 Monday.

Redundancies surfaced:
  - thirty_minutes == half_hour (explicit alias)
  - week == week_starting_sunday (identical Sunday-start SQL)
  - quarter == quarter_year (explicit alias)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

# ---------- Timestamp battery ----------
# Stresses: Sun/Mon boundary, month/quarter/year end/start, leap day, 2+ years
TIMESTAMPS = [
    "2023-12-31 23:45:37",  # Sunday, last day of month/quarter/year
    "2024-01-01 00:15:02",  # Monday, first day of month/quarter/year
    "2024-02-29 12:30:45",  # Leap day
    "2024-02-29 23:59:59",  # Leap day end
    "2024-03-01 00:00:01",  # Day after leap day
    "2024-03-31 18:22:33",  # End of Q1
    "2024-04-01 06:07:08",  # Start of Q2
    "2024-06-15 14:05:59",  # Saturday
    "2024-06-16 03:10:00",  # Sunday
    "2024-06-17 09:55:30",  # Monday
    "2024-07-17 11:23:47",  # Ordinary mid-week
    "2024-09-30 23:59:59",  # End of Q3
    "2024-10-01 00:00:00",  # Start of Q4
    "2024-12-31 23:59:59",  # End of year
    "2025-01-01 00:00:00",  # Start of next year
    "2025-03-15 07:33:22",  # Ordinary 2025
]

# ---------- Superset SQLite engine-spec expressions (verbatim from sqlite.py) ----------
GRAIN_SQL: dict[str, str] = {
    "second": "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:%S', {col}))",
    "five_seconds": (
        "DATETIME({col}, printf('-%d seconds', "
        "CAST(strftime('%S', {col}) AS INT) % 5))"
    ),
    "thirty_seconds": (
        "DATETIME({col}, printf('-%d seconds', "
        "CAST(strftime('%S', {col}) AS INT) % 30))"
    ),
    "minute": "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}))",
    "five_minutes": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 5))"
    ),
    "ten_minutes": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 10))"
    ),
    "fifteen_minutes": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 15))"
    ),
    "thirty_minutes": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 30))"
    ),
    "half_hour": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:%M:00', {col}), printf('-%d minutes', "
        "CAST(strftime('%M', {col}) AS INT) % 30))"
    ),
    "hour": "DATETIME(STRFTIME('%Y-%m-%dT%H:00:00', {col}))",
    "six_hours": (
        "DATETIME(STRFTIME('%Y-%m-%dT%H:00:00', {col}), printf('-%d hours', "
        "CAST(strftime('%H', {col}) AS INT) % 6))"
    ),
    "day": "DATETIME({col}, 'start of day')",
    "week": (
        "DATETIME({col}, 'start of day', -strftime('%w', {col}) || ' days')"
    ),
    "month": "DATETIME({col}, 'start of month')",
    "quarter": (
        "DATETIME({col}, 'start of month', "
        "printf('-%d month', (strftime('%m', {col}) - 1) % 3))"
    ),
    "quarter_year": (
        "DATETIME({col}, 'start of month', "
        "printf('-%d month', (strftime('%m', {col}) - 1) % 3))"
    ),
    "year": "DATETIME({col}, 'start of year')",
    "week_ending_saturday": (
        "DATETIME({col}, 'start of day', 'weekday 6')"
    ),
    "week_ending_sunday": (
        "DATETIME({col}, 'start of day', 'weekday 0')"
    ),
    "week_starting_sunday": (
        "DATETIME({col}, 'start of day', -strftime('%w', {col}) || ' days')"
    ),
    "week_starting_monday": (
        "DATETIME({col}, 'start of day', '-' || "
        "((strftime('%w', {col}) + 6) % 7) || ' days')"
    ),
}


# ---------- ISO-8601 reference computation ----------
def _iso_bucket(ts_str: str, grain: str) -> str:
    """Return the ISO-8601 expected bucket as 'YYYY-MM-DD HH:MM:SS'."""
    dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")

    if grain == "second":
        result = dt.replace(microsecond=0)
    elif grain == "five_seconds":
        result = dt.replace(second=(dt.second // 5) * 5, microsecond=0)
    elif grain == "thirty_seconds":
        result = dt.replace(second=(dt.second // 30) * 30, microsecond=0)
    elif grain == "minute":
        result = dt.replace(second=0, microsecond=0)
    elif grain == "five_minutes":
        result = dt.replace(minute=(dt.minute // 5) * 5, second=0, microsecond=0)
    elif grain == "ten_minutes":
        result = dt.replace(minute=(dt.minute // 10) * 10, second=0, microsecond=0)
    elif grain == "fifteen_minutes":
        result = dt.replace(
            minute=(dt.minute // 15) * 15, second=0, microsecond=0
        )
    elif grain in ("thirty_minutes", "half_hour"):
        result = dt.replace(
            minute=(dt.minute // 30) * 30, second=0, microsecond=0
        )
    elif grain == "hour":
        result = dt.replace(minute=0, second=0, microsecond=0)
    elif grain == "six_hours":
        result = dt.replace(
            hour=(dt.hour // 6) * 6, minute=0, second=0, microsecond=0
        )
    elif grain == "day":
        result = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elif grain in ("week", "week_starting_sunday"):
        # SQLite WEEK uses Sunday-start (%w: 0=Sun)
        days_since_sunday = (dt.weekday() + 1) % 7
        result = (dt - timedelta(days=days_since_sunday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif grain == "week_starting_monday":
        days_since_monday = dt.weekday()
        result = (dt - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif grain == "week_ending_saturday":
        # SQLite 'weekday 6' returns next Saturday (or same day if already Sat)
        days_ahead = (5 - dt.weekday()) % 7
        result = (dt + timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif grain == "week_ending_sunday":
        # SQLite 'weekday 0' returns next Sunday (or same day if already Sun)
        days_ahead = (6 - dt.weekday()) % 7
        result = (dt + timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif grain == "month":
        result = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif grain in ("quarter", "quarter_year"):
        q_month = ((dt.month - 1) // 3) * 3 + 1
        result = dt.replace(
            month=q_month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    elif grain == "year":
        result = dt.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    else:
        raise ValueError(f"Unknown grain: {grain}")

    return result.strftime("%Y-%m-%d %H:%M:%S")


# ---------- Fixture: live SQLite connection ----------
@pytest.fixture(scope="module")
def sqlite_conn() -> sqlite3.Connection:
    """Create an in-memory SQLite DB populated with the timestamp battery."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE ts_battery (ts TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO ts_battery (ts) VALUES (?)", [(t,) for t in TIMESTAMPS]
    )
    conn.commit()
    yield conn
    conn.close()


def _execute_grain(
    conn: sqlite3.Connection, grain: str
) -> list[tuple[str, str]]:
    """Execute a grain's SQL against the live DB, return (input, bucket) pairs."""
    sql_expr = GRAIN_SQL[grain].replace("{col}", "ts")
    rows = conn.execute(
        f"SELECT ts, {sql_expr} FROM ts_battery ORDER BY ts"
    ).fetchall()
    return rows


# ---------- Core grain tests: execute live and assert against expected ----------
@pytest.mark.parametrize(
    "grain",
    [
        "second",
        "five_seconds",
        "thirty_seconds",
        "minute",
        "five_minutes",
        "ten_minutes",
        "fifteen_minutes",
        "thirty_minutes",
        "half_hour",
        "hour",
        "six_hours",
        "day",
        "week",
        "month",
        "quarter",
        "quarter_year",
        "year",
        "week_ending_saturday",
        "week_ending_sunday",
        "week_starting_sunday",
        "week_starting_monday",
    ],
)
def test_grain_buckets_match_expected(
    sqlite_conn: sqlite3.Connection, grain: str
) -> None:
    """
    Execute the engine-spec SQL for `grain` against a live SQLite DB and
    assert the bucket matches the independently-computed expected value.

    For grains that diverge from ISO-8601 (e.g. WEEK uses Sunday-start),
    the expected value reflects the OBSERVED dialect convention so the test
    pins actual behavior.
    """
    rows = _execute_grain(sqlite_conn, grain)
    assert len(rows) == len(TIMESTAMPS)
    for ts_input, sql_bucket in rows:
        expected = _iso_bucket(ts_input, grain)
        assert sql_bucket == expected, (
            f"grain={grain}, input={ts_input}: "
            f"DB returned '{sql_bucket}', expected '{expected}'"
        )


# ---------- Redundancy tests: run BOTH expressions live, compare outputs ----------
@pytest.mark.parametrize(
    "grain_a,grain_b,reason",
    [
        ("thirty_minutes", "half_hour", "explicit alias in spec"),
        ("week", "week_starting_sunday", "identical Sunday-start SQL"),
        ("quarter", "quarter_year", "explicit alias in spec"),
    ],
)
def test_redundant_grains_produce_identical_buckets(
    sqlite_conn: sqlite3.Connection, grain_a: str, grain_b: str, reason: str
) -> None:
    """
    Execute BOTH grain expressions against the live DB and verify they
    produce identical bucket values for every timestamp in the battery.
    """
    rows_a = _execute_grain(sqlite_conn, grain_a)
    rows_b = _execute_grain(sqlite_conn, grain_b)
    assert len(rows_a) == len(rows_b) == len(TIMESTAMPS)
    for (ts_a, bucket_a), (ts_b, bucket_b) in zip(rows_a, rows_b):
        assert ts_a == ts_b
        assert bucket_a == bucket_b, (
            f"Redundancy ({grain_a} vs {grain_b}, reason: {reason}): "
            f"input={ts_a}, {grain_a}='{bucket_a}', {grain_b}='{bucket_b}'"
        )


# ---------- ISO-8601 discrepancy test: WEEK starts Sunday, not Monday ----------
def test_week_grain_uses_sunday_start_not_iso_monday(
    sqlite_conn: sqlite3.Connection,
) -> None:
    """
    Explicitly verify that the WEEK grain buckets to the preceding SUNDAY,
    diverging from ISO-8601's Monday-start convention.
    This is a SQLite dialect convention (strftime '%w' = 0 for Sunday),
    not a defect.
    """
    rows = _execute_grain(sqlite_conn, "week")
    for ts_input, sql_bucket in rows:
        dt_input = datetime.strptime(ts_input, "%Y-%m-%d %H:%M:%S")
        dt_bucket = datetime.strptime(sql_bucket, "%Y-%m-%d %H:%M:%S")
        # The bucket should always be a Sunday (weekday() == 6)
        assert dt_bucket.weekday() == 6, (
            f"WEEK bucket for {ts_input} is {sql_bucket} "
            f"(weekday={dt_bucket.weekday()}), expected Sunday (6)"
        )
        # ISO-8601 would give Monday; verify they differ when input is not Mon
        iso_monday = (dt_input - timedelta(days=dt_input.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if dt_input.weekday() != 0:  # not already Monday
            # Sunday-start ≠ Monday-start for non-Monday inputs
            assert dt_bucket != iso_monday, (
                f"Expected WEEK to diverge from ISO Monday for {ts_input}"
            )
