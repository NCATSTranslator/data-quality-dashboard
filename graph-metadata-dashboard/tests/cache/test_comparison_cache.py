from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from graph_metadata_dashboard.cache import MetadataCache
from graph_metadata_dashboard.cache.comparison import (
    load_comparison,
    load_schema_details,
    store_comparison,
)
from graph_metadata_dashboard.cache.disk import DiskMetadataCache
from graph_metadata_dashboard.cache.memory import InMemoryMetadataCache
from graph_metadata_dashboard.diff import ComparisonResult, compare
from graph_metadata_dashboard.diff.details import remaining_schema_changes
from graph_metadata_dashboard.parsers.graph_metadata import parse_graph_metadata
from tests.conftest import load_fixture


class RecordingCache:
    def __init__(self, backend: MetadataCache) -> None:
        self.backend = backend
        self.reads: list[str] = []

    def get(self, session_id: str, key: str) -> Any:
        self.reads.append(key)
        return self.backend.get(session_id, key)

    def set(self, session_id: str, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        self.backend.set(session_id, key, value, ttl_seconds=ttl_seconds)

    def delete(self, session_id: str, key: str) -> None:
        self.backend.delete(session_id, key)


@pytest.fixture(scope="module")
def large_comparison() -> ComparisonResult:
    return compare([
        parse_graph_metadata(
            load_fixture(f"{name}.graph-metadata.json"),
            schema_data=load_fixture("robokopkg.schema.json") if name == "robokopkg" else None,
        ) for name in ("alliance", "translator_kg_open", "robokopkg")
    ])


@pytest.mark.parametrize("backend", ["memory", "disk"])
def test_snapshots_survive_other_renders_and_remain_session_scoped(
    backend: str, tmp_path: Path,
) -> None:
    cache: MetadataCache = (
        InMemoryMetadataCache() if backend == "memory" else DiskMetadataCache(str(tmp_path), 3600)
    )
    graph = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    result = compare([graph, graph])
    first = store_comparison(cache, "session-a", result)
    other = store_comparison(cache, "session-b", result)

    assert load_comparison(cache, "session-a", first) == result
    assert load_comparison(cache, "session-b", first) is None
    other_graph = parse_graph_metadata(load_fixture("translator_kg_open.graph-metadata.json"))
    other_result = compare([other_graph, graph])
    replacement = store_comparison(cache, "session-a", other_result)
    assert replacement != first
    assert load_comparison(cache, "session-a", first) == result
    assert load_comparison(cache, "session-a", replacement) == other_result
    assert load_comparison(cache, "session-b", other) == result
    assert load_comparison(cache, None, replacement) is None
    assert load_comparison(cache, "session-b", None) is None


def test_snapshots_follow_cache_expiry(tmp_path: Path) -> None:
    cache = DiskMetadataCache(str(tmp_path), 0)
    graph = parse_graph_metadata(load_fixture("alliance.graph-metadata.json"))
    token = store_comparison(cache, "session-a", compare([graph, graph]))
    assert load_comparison(cache, "session-a", token) is None
    assert load_schema_details(cache, "session-a", token, 0, "node_changes") is None


@pytest.mark.parametrize("backend", ["memory", "disk"])
def test_schema_pages_read_only_requested_source_then_reuse_page(
    backend: str, tmp_path: Path, large_comparison: ComparisonResult,
) -> None:
    cache = RecordingCache(
        InMemoryMetadataCache() if backend == "memory" else DiskMetadataCache(str(tmp_path), 3600)
    )
    token = store_comparison(cache, "session", large_comparison)
    prefix = f"comparison:{token}"
    index = f"{prefix}:index"
    cases = [(1, "node_attribute_changes", 1), (1, "edge_changes", 1)]
    rows = large_comparison.comparisons[1].schema.node_changes
    row_index = max(range(len(rows)), key=lambda index: len(rows[index].attribute_changes))
    cases.append((1, f"node_changes/{row_index}/attribute_changes", 0))
    for pair, category, page in cases:
        cache.reads.clear()
        expected = remaining_schema_changes(large_comparison, pair, category, page)
        assert load_schema_details(cache, "session", token, pair, category, page) == expected
        page_key = f"{prefix}:page:{pair}:{category}:{page}"
        assert cache.reads == [index, page_key, f"{prefix}:source:{pair}:{category.split('/')[0]}"]
        cache.reads.clear()
        assert load_schema_details(cache, "session", token, pair, category, page) == expected
        assert cache.reads == [index, page_key]
    assert large_comparison.comparisons[1].schema.raw is not None
    assert load_comparison(cache, "session", token) == large_comparison
    assert load_schema_details(cache, "other-session", token, 1, "edge_changes") is None
    store_comparison(cache, "session", large_comparison)
    assert load_schema_details(cache, "session", token, 1, "edge_changes", 1) is not None
    cache.delete("session", index)
    cache.reads.clear()
    assert load_schema_details(cache, "session", token, 1, "edge_changes", 1) is None
    assert cache.reads == [index]


def test_schema_page_cache_handles_missing_sources_and_invalid_requests(
    large_comparison: ComparisonResult,
) -> None:
    cache = InMemoryMetadataCache()
    token = store_comparison(cache, "session", large_comparison)
    for pair, category, page in (
        (-1, "edge_changes", 0), (True, "edge_changes", 0), (99, "edge_changes", 0),
        (1, "raw", 0), (1, "node_changes/0/__dict__", 0), (1, None, 0),
        (1, "node_changes/9999/attribute_changes", 0), (1, "edge_changes", "1"),
    ):
        with pytest.raises(ValueError):
            load_schema_details(cache, "session", token, pair, category, page)
    for page in (-1, 99999):
        assert load_schema_details(cache, "session", token, 1, "edge_changes", page) == (
            remaining_schema_changes(large_comparison, 1, "edge_changes", page)
        )
    cache.delete("session", f"comparison:{token}:source:1:node_attribute_changes")
    assert load_schema_details(cache, "session", token, 1, "node_attribute_changes") is None
