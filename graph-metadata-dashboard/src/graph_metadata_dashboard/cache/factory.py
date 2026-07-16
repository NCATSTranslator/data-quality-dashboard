from __future__ import annotations

from graph_metadata_dashboard.cache.base import MetadataCache
from graph_metadata_dashboard.cache.disk import DiskMetadataCache
from graph_metadata_dashboard.config import Settings


def create_metadata_cache(settings: Settings) -> MetadataCache:
    if settings.cache_backend == "diskcache":
        return DiskMetadataCache(
            directory=settings.cache_dir,
            default_ttl_seconds=settings.cache_ttl_seconds,
        )
    msg = f"Unsupported metadata cache backend: {settings.cache_backend}"
    raise ValueError(msg)
