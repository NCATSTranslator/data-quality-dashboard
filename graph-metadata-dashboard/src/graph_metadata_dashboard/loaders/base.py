from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

JsonObject = dict[str, Any]


class MetadataSource(Protocol):
    @property
    def source_key(self) -> str: ...

    @property
    def label(self) -> str: ...

    def load_graph_metadata(self) -> JsonObject: ...

    def load_schema(self, schema_reference: str | None = None) -> JsonObject | None: ...


def ensure_json_object(value: Any, *, context: str) -> JsonObject:
    if not isinstance(value, Mapping):
        msg = f"{context} must be a JSON object"
        raise ValueError(msg)
    return dict(value)
