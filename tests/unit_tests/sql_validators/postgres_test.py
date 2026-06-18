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

from __future__ import annotations

from unittest.mock import MagicMock, patch

from superset.sql_validators.postgres import PostgreSQLValidator


def test_valid_sql_returns_empty_annotations() -> None:
    mock_database = MagicMock()
    with patch(
        "superset.sql_validators.postgres.check_string",
        return_value=(True, ""),
    ):
        annotations = PostgreSQLValidator.validate(
            sql="SELECT 1",
            catalog=None,
            schema=None,
            database=mock_database,
        )
    assert annotations == []


def test_invalid_sql_with_line_number() -> None:
    mock_database = MagicMock()
    with patch(
        "superset.sql_validators.postgres.check_string",
        return_value=(False, 'line 3: syntax error at or near "SELEC"'),
    ):
        annotations = PostgreSQLValidator.validate(
            sql="SELECT 1;\nSELECT 2;\nSELEC * FROM foo",
            catalog=None,
            schema=None,
            database=mock_database,
        )
    assert len(annotations) == 1
    assert annotations[0].line_number == 3
    assert 'syntax error at or near "SELEC"' in annotations[0].message
    assert annotations[0].start_column is None
    assert annotations[0].end_column is None


def test_invalid_sql_without_line_number() -> None:
    mock_database = MagicMock()
    with patch(
        "superset.sql_validators.postgres.check_string",
        return_value=(False, "some generic error message"),
    ):
        annotations = PostgreSQLValidator.validate(
            sql="bad sql",
            catalog=None,
            schema=None,
            database=mock_database,
        )
    assert len(annotations) == 1
    assert annotations[0].line_number is None
    assert annotations[0].message == "some generic error message"


def test_check_string_called_with_semicolon() -> None:
    mock_database = MagicMock()
    with patch(
        "superset.sql_validators.postgres.check_string",
        return_value=(True, ""),
    ) as mock_check:
        PostgreSQLValidator.validate(
            sql="SELECT 1",
            catalog=None,
            schema=None,
            database=mock_database,
        )
    mock_check.assert_called_once_with("SELECT 1", add_semicolon=True)


def test_validator_name() -> None:
    assert PostgreSQLValidator.name == "PostgreSQLValidator"


def test_get_validator_by_name_postgres() -> None:
    from superset.sql_validators import get_validator_by_name

    validator = get_validator_by_name("PostgreSQLValidator")
    assert validator is PostgreSQLValidator


def test_get_validator_by_name_unknown_returns_none() -> None:
    from superset.sql_validators import get_validator_by_name

    validator = get_validator_by_name("NonExistentValidator")
    assert validator is None
