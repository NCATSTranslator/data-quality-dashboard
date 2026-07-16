from __future__ import annotations

from typing import Any, Protocol


class MetadataCache(Protocol):
    """Server-side cache for metadata payloads, automatically scoped by session."""

    def get(self, session_id: str, key: str) -> Any | None:
        raise NotImplementedError

    def set(
        self,
        session_id: str,
        key: str,
        value: Any,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        raise NotImplementedError

    def delete(self, session_id: str, key: str) -> None:
        raise NotImplementedError
