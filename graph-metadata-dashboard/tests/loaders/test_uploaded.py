from __future__ import annotations

import base64
import json

import pytest

from graph_metadata_dashboard.loaders.uploaded import UploadedMetadata, decode_dash_upload


def test_decode_dash_upload_returns_json_object() -> None:
    payload = {"name": "example"}
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()

    assert decode_dash_upload(f"data:application/json;base64,{encoded}", context="graph") == payload


def test_decode_dash_upload_rejects_non_object_json() -> None:
    encoded = base64.b64encode(json.dumps(["not", "object"]).encode()).decode()

    with pytest.raises(ValueError, match="must be a JSON object"):
        decode_dash_upload(f"data:application/json;base64,{encoded}", context="graph")


def test_uploaded_metadata_returns_optional_schema() -> None:
    source = UploadedMetadata(graph_metadata={"name": "graph"}, schema={"nodes": []})

    assert source.load_graph_metadata() == {"name": "graph"}
    assert source.load_schema() == {"nodes": []}
