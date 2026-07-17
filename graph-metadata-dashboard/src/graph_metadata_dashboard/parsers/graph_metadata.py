from __future__ import annotations

from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Any

from graph_metadata_dashboard.parsers.models import (
    EdgeTriple,
    GraphSchema,
    JsonObject,
    KnowledgeSource,
    NodeCategory,
    ParsedGraphMetadata,
    SchemaReference,
    SubgraphSource,
    int_or_none,
)


def parse_graph_metadata(
    data: Mapping[str, Any],
    *,
    schema_data: Mapping[str, Any] | None = None,
) -> ParsedGraphMetadata:
    raw = dict(data)
    KGXGraphMetadata, _ = _orion_metadata_classes()
    kgx_metadata = KGXGraphMetadata.from_dict(raw)
    schema_reference = detect_schema_reference(raw)
    inline_schema = raw.get("schema") if schema_reference.kind == "inline" else None
    candidate_schema = schema_data or inline_schema
    schema = parse_schema(candidate_schema) if isinstance(candidate_schema, Mapping) else None

    return ParsedGraphMetadata(
        name=_call_or_default(kgx_metadata, "get_graph_name", raw.get("name", "")),
        release_version=_call_or_default(
            kgx_metadata, "get_release_version", raw.get("version", "")
        ),
        build_version=_call_or_default(kgx_metadata, "get_build_version", ""),
        build_time=_call_or_default(
            kgx_metadata, "get_build_time", raw.get("dateCreated", "")
        ),
        date_created=str(raw.get("dateCreated", "")),
        date_modified=str(raw.get("dateModified", "")),
        license=_string_or_empty(raw.get("license", None)),
        biolink_version=_call_or_default(
            kgx_metadata, "get_biolink_version", raw.get("biolinkVersion", "")
        ),
        babel_version=_call_or_default(
            kgx_metadata, "get_babel_version", raw.get("babelVersion", "")
        ),
        source_ids=tuple(_safe_iter_strings(_call_or_default(kgx_metadata, "get_source_ids", []))),
        knowledge_sources=tuple(
            _parse_knowledge_source(entry) for entry in _list(raw.get("isBasedOn"))
        ),
        subgraphs=tuple(_parse_subgraph(entry) for entry in _list(raw.get("hasPart"))),
        schema_reference=schema_reference,
        schema=schema,
        schema_version_marker=_string_or_empty(raw.get("biolinkVersion", None)),
        raw=raw,
    )


def detect_schema_reference(data: Mapping[str, Any]) -> SchemaReference:
    schema = data.get("schema")
    if not isinstance(schema, Mapping):
        return SchemaReference(kind="absent")
    schema_id = schema.get("@id")
    if isinstance(schema_id, str) and schema_id:
        return SchemaReference(kind="pointer", url=schema_id)
    if "nodes" in schema or "edges" in schema:
        return SchemaReference(kind="inline")
    return SchemaReference(kind="absent")


def parse_schema(data: Mapping[str, Any] | None) -> GraphSchema | None:
    if data is None:
        return None
    raw = dict(data)
    schema_body = _schema_body(raw)
    nodes = tuple(_parse_node_category(entry) for entry in _list(schema_body.get("nodes")))
    edges = tuple(_parse_edge_triple(entry) for entry in _list(schema_body.get("edges")))
    nodes_summary = dict(schema_body.get("nodes_summary") or {})
    edges_summary = dict(schema_body.get("edges_summary") or {})
    return GraphSchema(
        nodes=nodes,
        edges=edges,
        nodes_summary=nodes_summary,
        edges_summary=edges_summary,
        raw=raw,
    )


def _schema_body(raw: JsonObject) -> JsonObject:
    nested = raw.get("schema")
    if isinstance(nested, Mapping) and ("nodes" in nested or "edges" in nested):
        return dict(nested)
    return raw


def _parse_knowledge_source(entry: Mapping[str, Any]) -> KnowledgeSource:
    citation = entry.get("citation")
    citations = [str(item) for item in citation] if isinstance(citation, list) else []
    return KnowledgeSource(
        id=_string_or_empty(entry.get("id", None) or entry.get("@id", None)),
        name=_string_or_empty(entry.get("name", None)),
        description=_string_or_empty(entry.get("description", None)),
        license=_string_or_empty(entry.get("license", None)),
        attribution=_string_or_empty(entry.get("attribution", None)),
        citation=citations,
        version=_string_or_empty(entry.get("version", None)),
    )


def _parse_subgraph(entry: Mapping[str, Any]) -> SubgraphSource:
    _, KGXKnowledgeGraphSource = _orion_metadata_classes()
    kgx_source = KGXKnowledgeGraphSource.from_dict(dict(entry))
    return SubgraphSource(
        id=_string_or_empty(getattr(kgx_source, "id", entry.get("@id", ""))),
        name=_string_or_empty(getattr(kgx_source, "name", entry.get("name", ""))),
        node_count=int_or_none(
            getattr(kgx_source, "node_count", entry.get("orion:nodeCount"))
        ),
        edge_count=int_or_none(
            getattr(kgx_source, "edge_count", entry.get("orion:edgeCount"))
        ),
    )


def _parse_node_category(entry: Mapping[str, Any]) -> NodeCategory:
    category_value = entry.get("category", entry.get("categories", "Unknown"))
    if isinstance(category_value, list):
        category = ", ".join(str(item) for item in category_value)
    else:
        category = _string_or_empty(category_value)
    return NodeCategory(
        category=category,
        count=int_or_none(entry.get("count")) or 0,
        id_prefixes=_int_dict(entry.get("id_prefixes")),
        attributes=_int_dict(entry.get("attributes")),
    )


def _parse_edge_triple(entry: Mapping[str, Any]) -> EdgeTriple:
    return EdgeTriple(
        subject_category=tuple(_safe_iter_strings(entry.get("subject_category"))),
        predicate=_string_or_empty(entry.get("predicate")) or "unknown",
        object_category=tuple(_safe_iter_strings(entry.get("object_category"))),
        count=int_or_none(entry.get("count")) or 0,
        primary_knowledge_sources=_int_dict(entry.get("primary_knowledge_sources")),
        qualifiers=_int_dict(entry.get("qualifiers")),
        attributes=_int_dict(entry.get("attributes")),
        subject_id_prefixes=_int_dict(entry.get("subject_id_prefixes")),
        object_id_prefixes=_int_dict(entry.get("object_id_prefixes")),
    )


def _call_or_default(obj: Any, method_name: str, default: Any) -> str | list[str]:
    method = getattr(obj, method_name, None)
    if not callable(method):
        return default
    try:
        value = method()
    except Exception:
        return default
    return default if value is None or value == "" else value


def _list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _safe_iter_strings(value: Any) -> Iterable[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Iterable):
        return [str(item) for item in value if item is not None]
    return []


def _int_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    output: dict[str, int] = {}
    for key, count in value.items():
        safe_key = "Unknown" if key is None else str(key)
        parsed = int_or_none(count)
        if parsed is not None:
            output[safe_key] = parsed
    return output


def _string_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


@lru_cache(maxsize=1)
def _orion_metadata_classes() -> tuple[Any, Any]:
    # lazily import ORION when it is used
    from orion.kgx_metadata import KGXGraphMetadata, KGXKnowledgeGraphSource

    return KGXGraphMetadata, KGXKnowledgeGraphSource
