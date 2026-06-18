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

import pytest

from superset.async_events.async_query_manager import (
    AsyncQueryJobException,
    AsyncQueryManager,
    build_job_metadata,
    CacheBackendNotInitialized,
    get_cache_backend,
    increment_id,
    parse_event,
    UnsupportedCacheBackendError,
)
from superset.utils import json


def test_build_job_metadata_basic() -> None:
    result = build_job_metadata("channel-1", "job-1", 42)
    assert result == {
        "channel_id": "channel-1",
        "job_id": "job-1",
        "user_id": 42,
        "status": None,
        "errors": [],
        "result_url": None,
    }


def test_build_job_metadata_with_kwargs() -> None:
    result = build_job_metadata(
        "ch-2",
        "job-2",
        1,
        status="running",
        errors=["err1"],
        result_url="/api/result/123",
    )
    assert result["status"] == "running"
    assert result["errors"] == ["err1"]
    assert result["result_url"] == "/api/result/123"


def test_build_job_metadata_none_user_id() -> None:
    result = build_job_metadata("ch-3", "job-3", None)
    assert result["user_id"] is None


def test_parse_event() -> None:
    payload = json.dumps({"status": "done", "result_url": "/result"})
    event_data = ("1607477697866-0", {"data": payload})
    result = parse_event(event_data)
    assert result["id"] == "1607477697866-0"
    assert result["status"] == "done"
    assert result["result_url"] == "/result"


def test_increment_id_normal() -> None:
    assert increment_id("1607477697866-0") == "1607477697866-1"


def test_increment_id_high_suffix() -> None:
    assert increment_id("1607477697866-9") == "1607477697866-10"


def test_increment_id_invalid_returns_same() -> None:
    result = increment_id("")
    assert result == ""


def test_get_cache_backend_redis() -> None:
    config = {
        "GLOBAL_ASYNC_QUERIES_CACHE_BACKEND": {
            "CACHE_TYPE": "RedisCache",
            "CACHE_REDIS_HOST": "localhost",
            "CACHE_REDIS_PORT": 6379,
        }
    }
    from superset.async_events.cache_backend import RedisCacheBackend

    backend = get_cache_backend(config)
    assert isinstance(backend, RedisCacheBackend)


def test_get_cache_backend_unsupported_raises() -> None:
    config = {
        "GLOBAL_ASYNC_QUERIES_CACHE_BACKEND": {
            "CACHE_TYPE": "MemcachedCache",
        }
    }
    with pytest.raises(UnsupportedCacheBackendError):
        get_cache_backend(config)


def test_async_query_manager_init_job() -> None:
    manager = AsyncQueryManager()
    job = manager.init_job("channel-abc", 99)
    assert job["channel_id"] == "channel-abc"
    assert job["user_id"] == 99
    assert job["status"] == "pending"
    assert "job_id" in job


def test_async_query_manager_read_events_no_cache_raises() -> None:
    manager = AsyncQueryManager()
    with pytest.raises(CacheBackendNotInitialized):
        manager.read_events("channel-1", None)


def test_async_query_manager_update_job_no_cache_raises() -> None:
    manager = AsyncQueryManager()
    with pytest.raises(CacheBackendNotInitialized):
        manager.update_job({"channel_id": "ch-1", "job_id": "j-1"}, "running")


def test_async_query_manager_update_job_no_channel_id_raises() -> None:
    from unittest.mock import MagicMock

    manager = AsyncQueryManager()
    manager._cache = MagicMock()
    with pytest.raises(AsyncQueryJobException, match="No channel ID"):
        manager.update_job({"job_id": "j-1"}, "running")


def test_async_query_manager_update_job_no_job_id_raises() -> None:
    from unittest.mock import MagicMock

    manager = AsyncQueryManager()
    manager._cache = MagicMock()
    with pytest.raises(AsyncQueryJobException, match="No job ID"):
        manager.update_job({"channel_id": "ch-1"}, "running")


def test_async_query_manager_constants() -> None:
    assert AsyncQueryManager.STATUS_PENDING == "pending"
    assert AsyncQueryManager.STATUS_RUNNING == "running"
    assert AsyncQueryManager.STATUS_ERROR == "error"
    assert AsyncQueryManager.STATUS_DONE == "done"
    assert AsyncQueryManager.MAX_EVENT_COUNT == 100
