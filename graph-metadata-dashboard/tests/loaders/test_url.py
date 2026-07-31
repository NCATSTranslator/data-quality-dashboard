from __future__ import annotations

import socket
from typing import Any

import pytest
import requests

from graph_metadata_dashboard.loaders.url import UrlMetadata, UrlMetadataClient


class FakeResponse:
    def __init__(
        self,
        payload: bytes,
        *,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [
            self.payload[index : index + chunk_size]
            for index in range(0, len(self.payload), chunk_size)
        ]

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            error = requests.HTTPError(f"{self.status_code} error")
            error.response = self
            raise error

    def close(self) -> None:
        self.closed = True


def _allow_public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(
        host: str,
        port: int,
        *,
        type: socket.SocketKind,
    ) -> list[tuple[Any, Any, Any, Any, tuple[str, int]]]:
        del host, port, type
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


def test_url_metadata_client_loads_allowed_public_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_dns(monkeypatch)
    calls: list[tuple[str, float, bool, bool]] = []
    response = FakeResponse(b'{"name": "remote"}')

    def fake_get(
        url: str,
        *,
        timeout: float,
        stream: bool,
        allow_redirects: bool,
    ) -> FakeResponse:
        calls.append((url, timeout, stream, allow_redirects))
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    client = UrlMetadataClient(
        ("https://metadata.example/graphs",),
        timeout_seconds=3.0,
    )

    assert client.load_json("https://metadata.example/graphs/a/graph-metadata.json") == {
        "name": "remote"
    }
    assert calls == [
        ("https://metadata.example/graphs/a/graph-metadata.json", 3.0, True, False)
    ]
    assert response.closed is True


def test_url_metadata_client_rejects_unallowed_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_get(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("requests.get should not be called")

    monkeypatch.setattr(requests, "get", fail_get)
    client = UrlMetadataClient(("https://metadata.example/graphs",))

    with pytest.raises(ValueError, match="not allowed"):
        client.load_json("https://evil.example/graphs/a/graph-metadata.json")


def test_url_metadata_client_rejects_private_resolved_hosts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(
        host: str,
        port: int,
        *,
        type: socket.SocketKind,
    ) -> list[tuple[Any, Any, Any, Any, tuple[str, int]]]:
        del host, port, type
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    def fail_get(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("requests.get should not be called")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(requests, "get", fail_get)
    client = UrlMetadataClient(("https://metadata.example/graphs",))

    with pytest.raises(ValueError, match="public IP"):
        client.load_json("https://metadata.example/graphs/a/graph-metadata.json")


def test_url_metadata_client_blocks_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_public_dns(monkeypatch)
    response = FakeResponse(b"", status_code=302, headers={"location": "https://evil.example"})

    def fake_get(
        url: str,
        *,
        timeout: float,
        stream: bool,
        allow_redirects: bool,
    ) -> FakeResponse:
        del url, timeout, stream, allow_redirects
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    client = UrlMetadataClient(("https://metadata.example/graphs",))

    with pytest.raises(ValueError, match="redirects are not allowed"):
        client.load_json("https://metadata.example/graphs/a/graph-metadata.json")


def test_url_metadata_client_enforces_size_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_public_dns(monkeypatch)
    response = FakeResponse(b'{"name": "too-large"}', headers={"content-length": "200"})

    def fake_get(
        url: str,
        *,
        timeout: float,
        stream: bool,
        allow_redirects: bool,
    ) -> FakeResponse:
        del url, timeout, stream, allow_redirects
        return response

    monkeypatch.setattr(requests, "get", fake_get)
    client = UrlMetadataClient(("https://metadata.example/graphs",), max_bytes=10)

    with pytest.raises(ValueError, match="size limit"):
        client.load_json("https://metadata.example/graphs/a/graph-metadata.json")


def test_url_metadata_source_loads_optional_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_public_dns(monkeypatch)
    responses = {
        "https://metadata.example/graphs/a/graph-metadata.json": FakeResponse(
            b'{"name": "remote"}'
        ),
        "https://metadata.example/graphs/a/schema.json": FakeResponse(b'{"nodes": []}'),
    }

    def fake_get(
        url: str,
        *,
        timeout: float,
        stream: bool,
        allow_redirects: bool,
    ) -> FakeResponse:
        del timeout, stream, allow_redirects
        return responses[url]

    monkeypatch.setattr(requests, "get", fake_get)
    source = UrlMetadata(
        client=UrlMetadataClient(("https://metadata.example/graphs",)),
        graph_metadata_url="https://metadata.example/graphs/a/graph-metadata.json",
        schema_url="https://metadata.example/graphs/a/schema.json",
    )

    assert source.load_graph_metadata() == {"name": "remote"}
    assert source.load_schema() == {"nodes": []}
    assert source.source_key.startswith("url:")
