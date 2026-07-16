from __future__ import annotations

from graph_metadata_dashboard.cache.memory import InMemoryMetadataCache


def test_cache_namespaces_keys_by_session() -> None:
    cache = InMemoryMetadataCache()

    cache.set("session-a", "graph", {"name": "A"})
    cache.set("session-b", "graph", {"name": "B"})

    assert cache.get("session-a", "graph") == {"name": "A"}
    assert cache.get("session-b", "graph") == {"name": "B"}


def test_cache_delete_only_removes_session_key() -> None:
    cache = InMemoryMetadataCache()

    cache.set("session-a", "graph", 1)
    cache.set("session-b", "graph", 2)
    cache.delete("session-a", "graph")

    assert cache.get("session-a", "graph") is None
    assert cache.get("session-b", "graph") == 2
