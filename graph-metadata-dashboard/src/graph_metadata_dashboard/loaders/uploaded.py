from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from graph_metadata_dashboard.loaders.base import JsonObject, MetadataSource, ensure_json_object


@dataclass(frozen=True)
class UploadedMetadata(MetadataSource):
    graph_metadata: JsonObject
    schema: JsonObject | None = None
    filename: str = "uploaded graph-metadata.json"

    @property
    def source_key(self) -> str:
        return f"upload:{self.filename}"

    @property
    def label(self) -> str:
        return self.filename

    def load_graph_metadata(self) -> JsonObject:
        return self.graph_metadata

    def load_schema(self, schema_reference: str | None = None) -> JsonObject | None:
        del schema_reference
        return self.schema


def decode_dash_upload(contents: str, *, context: str) -> JsonObject:
    try:
        _, encoded = contents.split(",", 1)
        decoded = base64.b64decode(encoded)
        value: Any = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as error:
        msg = f"Could not decode {context} as JSON"
        raise ValueError(msg) from error
    return ensure_json_object(value, context=context)
