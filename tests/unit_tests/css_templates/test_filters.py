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

from unittest.mock import MagicMock

from superset.css_templates.filters import CssTemplateAllTextFilter


def test_filter_name() -> None:
    assert CssTemplateAllTextFilter.arg_name == "css_template_all_text"


def test_filter_apply_empty_value_returns_original_query() -> None:
    mock_query = MagicMock()
    filter_instance = CssTemplateAllTextFilter("template_name", datamodel=MagicMock())
    result = filter_instance.apply(mock_query, "")
    assert result == mock_query
    mock_query.filter.assert_not_called()


def test_filter_apply_none_value_returns_original_query() -> None:
    mock_query = MagicMock()
    filter_instance = CssTemplateAllTextFilter("template_name", datamodel=MagicMock())
    result = filter_instance.apply(mock_query, None)
    assert result == mock_query
    mock_query.filter.assert_not_called()


def test_filter_apply_with_value_calls_filter() -> None:
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    filter_instance = CssTemplateAllTextFilter("template_name", datamodel=MagicMock())
    result = filter_instance.apply(mock_query, "test_value")
    mock_query.filter.assert_called_once()
    assert result == mock_query
