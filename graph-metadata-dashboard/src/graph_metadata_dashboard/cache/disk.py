from __future__ import annotations

import logging
from typing import Any

import diskcache

from graph_metadata_dashboard.cache.base import MetadataCache

logger = logging.getLogger(__name__)


class DiskMetadataCache(MetadataCache):
    def __init__(self, directory: str, default_ttl_seconds: int) -> None:
        self._cache = diskcache.Cache(directory)
        self._default_ttl_seconds = default_ttl_seconds

    def get(self, session_id: str, key: str) -> Any | None:
        try:
            return self._cache.get(self._namespace(session_id, key))
        except Exception:
            logger.exception("Failed to read metadata cache key %s", key)
            return None

    def set(
        self,
        session_id: str,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        expire = ttl_seconds if ttl_seconds is not None else self._default_ttl_seconds
        try:
            self._cache.set(self._namespace(session_id, key), value, expire=expire)
        except Exception:
            logger.exception("Failed to write metadata cache key %s", key)

    def delete(self, session_id: str, key: str) -> None:
        try:
            del self._cache[self._namespace(session_id, key)]
        except KeyError:
            return
        except Exception:
            logger.exception("Failed to delete metadata cache key %s", key)

    @staticmethod
    def _namespace(session_id: str, key: str) -> str:
        return f"{session_id}:{key}"
