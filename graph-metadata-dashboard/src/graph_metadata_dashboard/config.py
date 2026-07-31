from __future__ import annotations

import os
from dataclasses import dataclass

from graph_metadata_dashboard.constants import (
    DEFAULT_KGX_STORAGE_BASE_URL,
    DEFAULT_REMOTE_METADATA_MAX_BYTES,
    DEFAULT_REQUESTS_TIMEOUT_SECONDS,
)

DEFAULT_REMOTE_METADATA_ALLOWED_PREFIXES = (
    DEFAULT_KGX_STORAGE_BASE_URL,
    "https://robokop.renci.org/graphs",
)


@dataclass(frozen=True)
class Settings:
    kgx_storage_base_url: str = DEFAULT_KGX_STORAGE_BASE_URL
    cache_backend: str = "diskcache"
    cache_dir: str = "/tmp/graph-metadata-dashboard-cache"
    cache_ttl_seconds: int = 60 * 60
    requests_timeout_seconds: float = DEFAULT_REQUESTS_TIMEOUT_SECONDS
    remote_metadata_allowed_url_prefixes: tuple[str, ...] = (
        DEFAULT_REMOTE_METADATA_ALLOWED_PREFIXES
    )
    remote_metadata_max_bytes: int = DEFAULT_REMOTE_METADATA_MAX_BYTES
    port: int = 8050
    debug: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        allowed_prefixes = _split_csv_env(
            "REMOTE_METADATA_ALLOWED_URL_PREFIXES",
            cls.remote_metadata_allowed_url_prefixes,
        )
        return cls(
            kgx_storage_base_url=os.getenv(
                "KGX_STORAGE_BASE_URL", cls.kgx_storage_base_url
            ).rstrip("/"),
            cache_backend=os.getenv("METADATA_CACHE_BACKEND", cls.cache_backend),
            cache_dir=os.getenv("METADATA_CACHE_DIR", cls.cache_dir),
            cache_ttl_seconds=int(os.getenv("METADATA_CACHE_TTL_SECONDS", cls.cache_ttl_seconds)),
            requests_timeout_seconds=float(
                os.getenv("REQUESTS_TIMEOUT_SECONDS", cls.requests_timeout_seconds)
            ),
            remote_metadata_allowed_url_prefixes=allowed_prefixes,
            remote_metadata_max_bytes=int(
                os.getenv("REMOTE_METADATA_MAX_BYTES", cls.remote_metadata_max_bytes)
            ),
            port=int(os.getenv("PORT", cls.port)),
            debug=os.getenv("DASH_DEBUG", "false").lower() in {"1", "true", "yes"},
        )


def _split_csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return tuple(value.strip().rstrip("/") for value in raw_value.split(",") if value.strip())
