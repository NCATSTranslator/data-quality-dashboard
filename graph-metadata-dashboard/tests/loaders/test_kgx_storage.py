from __future__ import annotations

from typing import Any

import pytest
import requests

from graph_metadata_dashboard.loaders.kgx_storage import (
    KgxRelease,
    KgxStorageClient,
    KgxStorageRelease,
    release_from_ui_value,
)


class FakeResponse:
    def __init__(self, payload: Any, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error


def _mock_get(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, FakeResponse],
) -> list[tuple[str, float]]:
    calls: list[tuple[str, float]] = []

    def fake_get(url: str, *, timeout: float) -> FakeResponse:
        calls.append((url, timeout))
        response = responses.get(url)
        if response is None:
            raise AssertionError(f"Unexpected URL fetched: {url}")
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    return calls


def test_latest_releases_parses_valid_manifest_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = "https://kgx-storage.example/releases"
    _mock_get(
        monkeypatch,
        {
            f"{base_url}/latest-release-summary.json": FakeResponse(
                {
                    "zeta": {
                        "release_version": "2026_02_01",
                        "data": f"{base_url}/zeta/2026_02_01/",
                    },
                    "alpha": {
                        "release_version": "2026_01_01",
                        "data": f"{base_url}/alpha/2026_01_01",
                    },
                    "invalid": {"data": f"{base_url}/invalid/2026_01_01"},
                }
            )
        },
    )

    releases = KgxStorageClient(base_url).latest_releases()

    assert [release.source_id for release in releases] == ["alpha", "zeta"]
    assert releases[0].data_url == f"{base_url}/alpha/2026_01_01"
    assert releases[0].label == "alpha (2026_01_01)"


def test_release_for_source_accepts_nested_or_flat_manifest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "https://kgx-storage.example/releases"
    _mock_get(
        monkeypatch,
        {
            f"{base_url}/alpha/latest-release.json": FakeResponse(
                {
                    "alpha": {
                        "release_version": "2026_01_01",
                        "data": f"{base_url}/alpha/2026_01_01",
                    }
                }
            ),
            f"{base_url}/beta/latest-release.json": FakeResponse(
                {
                    "release_version": "2026_02_01",
                    "data": f"{base_url}/beta/2026_02_01",
                }
            ),
        },
    )
    client = KgxStorageClient(base_url)

    alpha = client.release_for_source("alpha")
    beta = client.release_for_source("beta")

    assert alpha == KgxRelease("alpha", "2026_01_01", f"{base_url}/alpha/2026_01_01")
    assert beta == KgxRelease("beta", "2026_02_01", f"{base_url}/beta/2026_02_01")


def test_load_release_graph_metadata_preserves_release_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_url = "https://kgx-storage.example/releases"
    metadata_url = f"{base_url}/alpha/2026_01_01/graph-metadata.json"
    calls = _mock_get(monkeypatch, {metadata_url: FakeResponse({"name": "alpha"})})
    client = KgxStorageClient(base_url, timeout_seconds=3.5)

    payload = client.load_release_graph_metadata(
        KgxRelease("alpha", "2026_01_01", f"{base_url}/alpha/2026_01_01")
    )

    assert payload == {"name": "alpha"}
    assert calls == [(metadata_url, 3.5)]


def test_load_release_schema_returns_none_for_404(monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = "https://kgx-storage.example/releases"
    schema_url = f"{base_url}/alpha/2026_01_01/schema.json"
    _mock_get(monkeypatch, {schema_url: FakeResponse({"error": "missing"}, status_code=404)})
    client = KgxStorageClient(base_url)

    schema = client.load_release_schema(
        KgxRelease("alpha", "2026_01_01", f"{base_url}/alpha/2026_01_01")
    )

    assert schema is None


def test_fetch_url_must_remain_under_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_get(url: str, *, timeout: float) -> None:
        del url, timeout
        raise AssertionError("requests.get should not be called for rejected URLs")

    monkeypatch.setattr(requests, "get", fail_get)
    client = KgxStorageClient("https://kgx-storage.example/releases")

    with pytest.raises(ValueError, match="constrained for security"):
        client.load_release_graph_metadata(
            KgxRelease(
                "evil",
                "latest",
                "https://kgx-storage.example/releases-evil/alpha/latest",
            )
        )

    with pytest.raises(ValueError, match="constrained for security"):
        client.load_release_schema(
            KgxRelease("evil", "latest", "https://kgx-storage.example/releases/alpha/latest"),
            "https://evil.example/releases/alpha/latest/schema.json",
        )


def test_get_json_rejects_non_object_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    base_url = "https://kgx-storage.example/releases"
    url = f"{base_url}/latest-release-summary.json"
    _mock_get(monkeypatch, {url: FakeResponse(["not", "object"])})

    with pytest.raises(ValueError, match="must be a JSON object"):
        KgxStorageClient(base_url).latest_releases()


def test_kgx_storage_release_delegates_to_client() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.graph_loaded = False
            self.schema_reference: str | None = None

        def load_release_graph_metadata(self, release: KgxRelease) -> dict[str, str]:
            assert release.source_id == "alpha"
            self.graph_loaded = True
            return {"name": "alpha"}

        def load_release_schema(
            self,
            release: KgxRelease,
            schema_reference: str | None = None,
        ) -> dict[str, str]:
            assert release.source_id == "alpha"
            self.schema_reference = schema_reference
            return {"schema": "alpha"}

    client = FakeClient()
    release = KgxStorageRelease(
        client=client,  # type: ignore[arg-type]
        release=KgxRelease("alpha", "2026_01_01", "https://kgx-storage.example/releases/a"),
    )

    assert release.source_key == "kgx:alpha:2026_01_01"
    assert release.label == "alpha (2026_01_01)"
    assert release.load_graph_metadata() == {"name": "alpha"}
    assert release.load_schema("schema.json") == {"schema": "alpha"}
    assert client.graph_loaded is True
    assert client.schema_reference == "schema.json"


def test_release_from_ui_value_returns_matching_release() -> None:
    releases = [
        KgxRelease("alpha", "2026_01_01", "https://kgx-storage.example/releases/a"),
        KgxRelease("beta", "2026_02_01", "https://kgx-storage.example/releases/b"),
    ]

    assert release_from_ui_value("beta", releases) is releases[1]
    with pytest.raises(ValueError, match="Unknown KGX source"):
        release_from_ui_value("missing", releases)
