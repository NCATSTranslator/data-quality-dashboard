from __future__ import annotations

from typing import Any

from graph_metadata_dashboard.cache.base import MetadataCache


class InMemoryMetadataCache(MetadataCache):
    """Small test double for callback and cache interface tests."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def get(self, session_id: str, key: str) -> Any | None:
        return self._values.get(self._namespace(session_id, key))

    def set(self, session_id: str, key: str, value: Any, *,
        ttl_seconds: int | None = None,
    ) -> None:
        del ttl_seconds  # silence linter warning of unused variable
        self._values[self._namespace(session_id, key)] = value

    def delete(self, session_id: str, key: str) -> None:
        self._values.pop(self._namespace(session_id, key), None)

    @staticmethod
    def _namespace(session_id: str, key: str) -> str:
        return f"{session_id}:{key}"
