from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests

from graph_metadata_dashboard.loaders.base import JsonObject, MetadataSource, ensure_json_object


@dataclass(frozen=True)
class KgxRelease:
    source_id: str
    release_version: str
    data_url: str

    @property
    def label(self) -> str:
        return f"{self.source_id} ({self.release_version})"


class KgxStorageClient:
    def __init__(self, base_url: str, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def latest_releases(self) -> list[KgxRelease]:
        data = self._get_json(f"{self.base_url}/latest-release-summary.json")
        releases: list[KgxRelease] = []
        for source_id, entry in data.items():
            if not isinstance(entry, dict):
                continue
            data_url = entry.get("data")
            release_version = entry.get("release_version")
            if isinstance(data_url, str) and isinstance(release_version, str):
                releases.append(
                    KgxRelease(
                        source_id=str(source_id),
                        release_version=release_version,
                        data_url=data_url.rstrip("/"),
                    )
                )
        return sorted(releases, key=lambda release: release.source_id)

    def release_for_source(self, source_id: str) -> KgxRelease:
        data = self._get_json(f"{self.base_url}/{source_id}/latest-release.json")
        entry = data.get(source_id, data)
        if not isinstance(entry, dict):
            msg = f"Invalid release manifest for {source_id}"
            raise ValueError(msg)
        data_url = entry.get("data")
        release_version = entry.get("release_version")
        if not isinstance(data_url, str) or not isinstance(release_version, str):
            msg = f"Release manifest for {source_id} is missing data or release_version"
            raise ValueError(msg)
        return KgxRelease(source_id=source_id, release_version=release_version, data_url=data_url)

    def load_release_graph_metadata(self, release: KgxRelease) -> JsonObject:
        return self._get_json(urljoin(f"{release.data_url}", "graph-metadata.json"))

    def load_release_schema(self, release: KgxRelease,
        schema_reference: str | None = None,
    ) -> JsonObject | None:
        schema_url = schema_reference or urljoin(f"{release.data_url}", "schema.json")
        try:
            return self._get_json(schema_url)
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                return None
            raise

    def _get_json(self, url: str) -> JsonObject:
        self._validate_fetch_url(url)
        response = requests.get(url, timeout=self.timeout_seconds)
        response.raise_for_status()
        return ensure_json_object(response.json(), context=url)

    @staticmethod
    def _validate_fetch_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            msg = f"invalid metadata URL: {url}"
            raise ValueError(msg)


@dataclass(frozen=True)
class KgxStorageRelease(MetadataSource):
    client: KgxStorageClient
    release: KgxRelease

    @property
    def source_key(self) -> str:
        return f"kgx:{self.release.source_id}:{self.release.release_version}"

    @property
    def label(self) -> str:
        return self.release.label

    def load_graph_metadata(self) -> JsonObject:
        return self.client.load_release_graph_metadata(self.release)

    def load_schema(self, schema_reference: str | None = None) -> JsonObject | None:
        return self.client.load_release_schema(self.release, schema_reference)


def release_from_ui_value(value: str, releases: list[KgxRelease]) -> KgxRelease:
    for release in releases:
        if value == release.source_id:
            return release
    msg = f"Unknown KGX source: {value}"
    raise ValueError(msg)
