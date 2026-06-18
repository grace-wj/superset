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

from superset.async_events.cache_backend import (
    RedisCacheBackend,
    RedisSentinelCacheBackend,
)


def test_redis_cache_backend_from_config_defaults() -> None:
    config: dict[str, object] = {}
    with patch("superset.async_events.cache_backend.redis.Redis"):
        backend = RedisCacheBackend.from_config(config)
    assert isinstance(backend, RedisCacheBackend)


def test_redis_cache_backend_from_config_custom() -> None:
    config = {
        "CACHE_REDIS_HOST": "redis.example.com",
        "CACHE_REDIS_PORT": 6380,
        "CACHE_REDIS_DB": 2,
        "CACHE_REDIS_PASSWORD": "secret",
        "CACHE_KEY_PREFIX": "myprefix:",
        "CACHE_DEFAULT_TIMEOUT": 600,
        "CACHE_REDIS_SSL": True,
        "CACHE_REDIS_SSL_CERTFILE": "/path/cert.pem",
        "CACHE_REDIS_SSL_KEYFILE": "/path/key.pem",
        "CACHE_REDIS_SSL_CERT_REQS": "optional",
        "CACHE_REDIS_SSL_CA_CERTS": "/path/ca.pem",
    }
    with patch("superset.async_events.cache_backend.redis.Redis") as mock_redis:
        backend = RedisCacheBackend.from_config(config)
    assert isinstance(backend, RedisCacheBackend)
    # The Redis constructor is called twice: once via the parent class and once
    # directly in __init__ with SSL params. Verify the SSL call.
    calls = mock_redis.call_args_list
    assert len(calls) == 2
    ssl_call = calls[1]
    assert ssl_call.kwargs["host"] == "redis.example.com"
    assert ssl_call.kwargs["port"] == 6380
    assert ssl_call.kwargs["ssl"] is True
    assert ssl_call.kwargs["ssl_certfile"] == "/path/cert.pem"


def test_redis_cache_backend_from_config_with_username() -> None:
    config = {
        "CACHE_REDIS_USER": "myuser",
    }
    with patch("superset.async_events.cache_backend.redis.Redis"):
        backend = RedisCacheBackend.from_config(config)
    assert isinstance(backend, RedisCacheBackend)


def test_redis_cache_backend_max_event_count() -> None:
    assert RedisCacheBackend.MAX_EVENT_COUNT == 100


def test_redis_cache_backend_set() -> None:
    with patch("superset.async_events.cache_backend.redis.Redis") as mock_redis_cls:
        mock_redis = MagicMock()
        mock_redis_cls.return_value = mock_redis
        backend = RedisCacheBackend.from_config({})
        backend.set("key1", "value1", ex=60)
    mock_redis.set.assert_called_once_with(
        "key1", "value1", ex=60, px=None, nx=False, xx=False
    )


def test_redis_cache_backend_delete() -> None:
    with patch("superset.async_events.cache_backend.redis.Redis") as mock_redis_cls:
        mock_redis = MagicMock()
        mock_redis_cls.return_value = mock_redis
        backend = RedisCacheBackend.from_config({})
        backend.delete("key1", "key2")
    mock_redis.delete.assert_called_once_with("key1", "key2")


def test_redis_cache_backend_publish() -> None:
    with patch("superset.async_events.cache_backend.redis.Redis") as mock_redis_cls:
        mock_redis = MagicMock()
        mock_redis_cls.return_value = mock_redis
        backend = RedisCacheBackend.from_config({})
        backend.publish("channel", "message")
    mock_redis.publish.assert_called_once_with("channel", "message")


def test_redis_cache_backend_xadd() -> None:
    with patch("superset.async_events.cache_backend.redis.Redis") as mock_redis_cls:
        mock_redis = MagicMock()
        mock_redis_cls.return_value = mock_redis
        backend = RedisCacheBackend.from_config({})
        backend.xadd("stream", {"data": "value"}, "*", 1000)
    mock_redis.xadd.assert_called_once_with("stream", {"data": "value"}, "*", 1000)


def test_redis_cache_backend_xrange_default_count() -> None:
    with patch("superset.async_events.cache_backend.redis.Redis") as mock_redis_cls:
        mock_redis = MagicMock()
        mock_redis_cls.return_value = mock_redis
        backend = RedisCacheBackend.from_config({})
        backend.xrange("stream", "-", "+")
    mock_redis.xrange.assert_called_once_with(
        "stream", "-", "+", RedisCacheBackend.MAX_EVENT_COUNT
    )


def test_redis_cache_backend_xrange_custom_count() -> None:
    with patch("superset.async_events.cache_backend.redis.Redis") as mock_redis_cls:
        mock_redis = MagicMock()
        mock_redis_cls.return_value = mock_redis
        backend = RedisCacheBackend.from_config({})
        backend.xrange("stream", "-", "+", count=50)
    mock_redis.xrange.assert_called_once_with("stream", "-", "+", 50)


def test_redis_sentinel_cache_backend_from_config_defaults() -> None:
    with patch("superset.async_events.cache_backend.Sentinel") as mock_sentinel_cls:
        mock_sentinel = MagicMock()
        mock_sentinel_cls.return_value = mock_sentinel
        mock_sentinel.master_for.return_value = MagicMock()
        config: dict[str, object] = {}
        backend = RedisSentinelCacheBackend.from_config(config)
    assert isinstance(backend, RedisSentinelCacheBackend)


def test_redis_sentinel_cache_backend_max_event_count() -> None:
    assert RedisSentinelCacheBackend.MAX_EVENT_COUNT == 100
