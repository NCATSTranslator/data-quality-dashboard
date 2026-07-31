from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from graph_metadata_dashboard.constants import (
    DEFAULT_REMOTE_METADATA_MAX_BYTES,
    DEFAULT_REQUESTS_TIMEOUT_SECONDS,
)
from graph_metadata_dashboard.loaders.base import JsonObject, MetadataSource, ensure_json_object

_CHUNK_SIZE = 64 * 1024


@dataclass(frozen=True)
class UrlMetadataClient:
    allowed_prefixes: tuple[str, ...]
    timeout_seconds: float = DEFAULT_REQUESTS_TIMEOUT_SECONDS
    max_bytes: int = DEFAULT_REMOTE_METADATA_MAX_BYTES

    def __init__(
        self,
        allowed_prefixes: Sequence[str],
        *,
        timeout_seconds: float = DEFAULT_REQUESTS_TIMEOUT_SECONDS,
        max_bytes: int = DEFAULT_REMOTE_METADATA_MAX_BYTES,
    ) -> None:
        normalized_prefixes = tuple(
            prefix.rstrip("/")
            for prefix in allowed_prefixes
            if isinstance(prefix, str) and prefix.strip()
        )
        object.__setattr__(self, "allowed_prefixes", normalized_prefixes)
        object.__setattr__(self, "timeout_seconds", timeout_seconds)
        object.__setattr__(self, "max_bytes", max_bytes)

    def load_json(self, url: str) -> JsonObject:
        safe_url = self._validate_url(url)
        response = requests.get(
            safe_url,
            timeout=self.timeout_seconds,
            stream=True,
            allow_redirects=False,
        )
        try:
            if 300 <= response.status_code < 400:
                msg = "Remote metadata redirects are not allowed"
                raise ValueError(msg)
            response.raise_for_status()
            raw = self._read_limited_response(response, safe_url)
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError as error:
            msg = f"Could not decode remote metadata as JSON: {safe_url}"
            raise ValueError(msg) from error
        return ensure_json_object(value, context=safe_url)

    def _validate_url(self, url: str) -> str:
        safe_url = url.strip()
        parsed = urlparse(safe_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
            msg = "Remote metadata URL must be an absolute http(s) URL"
            raise ValueError(msg)
        if parsed.username or parsed.password or parsed.fragment:
            msg = "Remote metadata URL must not include credentials or fragments"
            raise ValueError(msg)
        if not self._matches_allowed_prefix(parsed):
            allowed = ", ".join(self.allowed_prefixes) or "no configured prefixes"
            msg = f"Remote metadata URL is not allowed. Allowed prefixes: {allowed}"
            raise ValueError(msg)
        self._validate_public_host(parsed.hostname, parsed.port, parsed.scheme)
        return safe_url

    def _matches_allowed_prefix(self, parsed_url: Any) -> bool:
        for prefix in self.allowed_prefixes:
            parsed_prefix = urlparse(prefix)
            if parsed_prefix.scheme not in {"http", "https"} or not parsed_prefix.netloc:
                continue
            if parsed_url.scheme != parsed_prefix.scheme:
                continue
            if parsed_url.netloc.lower() != parsed_prefix.netloc.lower():
                continue
            prefix_path = parsed_prefix.path.rstrip("/")
            if not prefix_path:
                return True
            if parsed_url.path == prefix_path or parsed_url.path.startswith(f"{prefix_path}/"):
                return True
        return False

    @staticmethod
    def _validate_public_host(hostname: str, port: int | None, scheme: str) -> None:
        default_port = 443 if scheme == "https" else 80
        try:
            addresses = socket.getaddrinfo(
                hostname,
                port or default_port,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as error:
            msg = f"Could not resolve remote metadata host: {hostname}"
            raise ValueError(msg) from error

        for address in addresses:
            ip_value = address[4][0]
            ip_address = ipaddress.ip_address(ip_value)
            if not ip_address.is_global:
                msg = "Remote metadata host must resolve only to public IP addresses"
                raise ValueError(msg)

    def _read_limited_response(self, response: requests.Response, url: str) -> bytes:
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                expected_size = int(content_length)
            except ValueError:
                expected_size = 0
            if expected_size > self.max_bytes:
                msg = f"Remote metadata exceeds the configured size limit: {url}"
                raise ValueError(msg)

        chunks: list[bytes] = []
        total_size = 0
        for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
            if not chunk:
                continue
            total_size += len(chunk)
            if total_size > self.max_bytes:
                msg = f"Remote metadata exceeds the configured size limit: {url}"
                raise ValueError(msg)
            chunks.append(chunk)
        return b"".join(chunks)


@dataclass(frozen=True)
class UrlMetadata(MetadataSource):
    client: UrlMetadataClient
    graph_metadata_url: str
    schema_url: str | None = None

    @property
    def source_key(self) -> str:
        digest = hashlib.sha256(self.graph_metadata_url.encode()).hexdigest()[:16]
        return f"url:{digest}"

    @property
    def label(self) -> str:
        parsed = urlparse(self.graph_metadata_url)
        return parsed.path.rsplit("/", 1)[-1] or parsed.netloc

    def load_graph_metadata(self) -> JsonObject:
        return self.client.load_json(self.graph_metadata_url)

    def load_schema(self, schema_reference: str | None = None) -> JsonObject | None:
        url = schema_reference or self.schema_url
        return self.client.load_json(url) if url else None
