from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    kgx_storage_base_url: str = "https://kgx-storage.ci.transltr.io/releases"
    cache_backend: str = "diskcache"
    cache_dir: str = "/tmp/graph-metadata-dashboard-cache"
    cache_ttl_seconds: int = 60 * 60
    requests_timeout_seconds: float = 20.0
    port: int = 8050
    debug: bool = False

    @classmethod
    def from_env(cls) -> Settings:
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
            port=int(os.getenv("PORT", cls.port)),
            debug=os.getenv("DASH_DEBUG", "false").lower() in {"1", "true", "yes"},
        )
