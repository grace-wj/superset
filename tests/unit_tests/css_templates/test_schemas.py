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

from superset.css_templates.schemas import (
    get_delete_ids_schema,
    openapi_spec_methods_override,
)


def test_get_delete_ids_schema_structure() -> None:
    assert get_delete_ids_schema["type"] == "array"
    items = get_delete_ids_schema["items"]
    assert isinstance(items, dict)
    assert items["type"] == "integer"


def test_openapi_spec_methods_override_has_get() -> None:
    assert "get" in openapi_spec_methods_override
    assert "get" in openapi_spec_methods_override["get"]
    assert "summary" in openapi_spec_methods_override["get"]["get"]


def test_openapi_spec_methods_override_has_get_list() -> None:
    assert "get_list" in openapi_spec_methods_override
    assert "get" in openapi_spec_methods_override["get_list"]
    assert "summary" in openapi_spec_methods_override["get_list"]["get"]
    assert "description" in openapi_spec_methods_override["get_list"]["get"]


def test_openapi_spec_methods_override_has_post() -> None:
    assert "post" in openapi_spec_methods_override
    assert "post" in openapi_spec_methods_override["post"]
    assert "summary" in openapi_spec_methods_override["post"]["post"]


def test_openapi_spec_methods_override_has_put() -> None:
    assert "put" in openapi_spec_methods_override
    assert "put" in openapi_spec_methods_override["put"]
    assert "summary" in openapi_spec_methods_override["put"]["put"]


def test_openapi_spec_methods_override_has_delete() -> None:
    assert "delete" in openapi_spec_methods_override
    assert "delete" in openapi_spec_methods_override["delete"]
    assert "summary" in openapi_spec_methods_override["delete"]["delete"]


def test_openapi_spec_methods_override_has_info() -> None:
    assert "info" in openapi_spec_methods_override
    assert "get" in openapi_spec_methods_override["info"]
    assert "summary" in openapi_spec_methods_override["info"]["get"]
