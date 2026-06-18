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

from unittest.mock import MagicMock

import pytest

from superset.sql_validators.base import BaseSQLValidator, SQLValidationAnnotation


def test_annotation_to_dict_all_fields() -> None:
    annotation = SQLValidationAnnotation(
        message="syntax error",
        line_number=5,
        start_column=10,
        end_column=15,
    )
    result = annotation.to_dict()
    assert result == {
        "message": "syntax error",
        "line_number": 5,
        "start_column": 10,
        "end_column": 15,
    }


def test_annotation_to_dict_none_fields() -> None:
    annotation = SQLValidationAnnotation(
        message="error",
        line_number=None,
        start_column=None,
        end_column=None,
    )
    result = annotation.to_dict()
    assert result["line_number"] is None
    assert result["start_column"] is None
    assert result["end_column"] is None
    assert result["message"] == "error"


def test_annotation_attributes() -> None:
    annotation = SQLValidationAnnotation(
        message="test msg",
        line_number=1,
        start_column=2,
        end_column=3,
    )
    assert annotation.message == "test msg"
    assert annotation.line_number == 1
    assert annotation.start_column == 2
    assert annotation.end_column == 3


def test_base_validator_validate_raises_not_implemented() -> None:
    mock_database = MagicMock()
    with pytest.raises(NotImplementedError):
        BaseSQLValidator.validate(
            sql="SELECT 1",
            catalog=None,
            schema=None,
            database=mock_database,
        )


def test_base_validator_name() -> None:
    assert BaseSQLValidator.name == "BaseSQLValidator"
