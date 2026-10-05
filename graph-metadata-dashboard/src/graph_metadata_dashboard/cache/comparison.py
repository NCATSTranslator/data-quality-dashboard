from __future__ import annotations

from uuid import uuid4

from graph_metadata_dashboard.cache.base import MetadataCache
from graph_metadata_dashboard.diff import ComparisonResult
from graph_metadata_dashboard.diff.details import (
    SCHEMA_SECTIONS,
    SchemaChangeDetails,
    SchemaChangeSource,
    schema_change_page,
    schema_change_source,
    schema_detail_source,
)


def store_comparison(cache: MetadataCache, session_id: str, result: ComparisonResult) -> str:
    """Keep each rendered comparison addressable until the cache's normal expiry."""
    token = uuid4().hex
    cache.set(session_id, f"comparison:{token}:index", len(result.comparisons))
    cache.set(session_id, f"comparison:{token}", result)
    for pair_index in range(len(result.comparisons)):
        for category in SCHEMA_SECTIONS:
            cache.set(
                session_id, f"comparison:{token}:source:{pair_index}:{category}",
                schema_change_source(result, pair_index, category),
            )
    return token


def load_comparison(
    cache: MetadataCache, session_id: str | None, token: str | None,
) -> ComparisonResult | None:
    if not session_id or not token:
        return None
    result = cache.get(session_id, f"comparison:{token}")
    return result if isinstance(result, ComparisonResult) else None


def load_schema_details(
    cache: MetadataCache, session_id: str | None, token: str | None,
    pair_index: int, category: str, page_index: int = 0,
) -> SchemaChangeDetails | None:
    if not session_id or not token:
        return None
    pair_count = cache.get(session_id, f"comparison:{token}:index")
    if type(pair_count) is not int:
        return None
    if type(pair_index) is not int or not 0 <= pair_index < pair_count:
        raise ValueError("Unknown graph comparison.")
    if not isinstance(category, str) or category.split("/")[0] not in SCHEMA_SECTIONS:
        raise ValueError("Unknown schema category.")
    if type(page_index) is not int:
        raise ValueError("Invalid page number.")
    prefix = f"comparison:{token}:page:{pair_index}:{category}:"
    cached = cache.get(session_id, f"{prefix}{page_index}")
    if isinstance(cached, SchemaChangeDetails):
        return cached
    section = category.split("/")[0]
    source = cache.get(session_id, f"comparison:{token}:source:{pair_index}:{section}")
    if not isinstance(source, SchemaChangeSource):
        return None
    details = schema_change_page(schema_detail_source(source, category), page_index)
    cache.set(session_id, f"{prefix}{details.page_index}", details)
    return details
