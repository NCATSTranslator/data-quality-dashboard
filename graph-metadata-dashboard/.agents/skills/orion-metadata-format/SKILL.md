---
name: orion-metadata-format
description: Exact shapes of ORION's graph-metadata.json and schema.json, parsing gotchas (hasPart, isBasedOn, pointer-vs-inline schema), which ORION classes to use, and the internal ParsedGraphMetadata/GraphSchema representation. Load before touching parsers/, before writing any code that reads raw metadata or schema JSON fields, or before adding a new adapter for a metadata shape.
---

# ORION metadata format & parser layer

## Parsing graph-metadata.json — use ORION's own classes

- `KGXGraphMetadata.from_dict(data)` parses a `graph-metadata.json` dict directly. Confirmed safe
  to import and use without `ORION_STORAGE`/`ORION_GRAPHS` env vars set (see "Import-time risk"
  below). It exposes ready-made accessors — `get_release_version()`, `get_build_version()`,
  `get_biolink_version()`, `get_babel_version()`, `get_graph_name()`, `get_build_time()`,
  `get_source_ids()` — use these instead of reading dict/JSON-LD keys directly.
- `hasPart` entries need a separate step: `KGXGraphMetadata.from_dict()` leaves them as raw dicts.
  Call `KGXKnowledgeGraphSource.from_dict(entry)` per entry to get typed `node_count`/`edge_count`.
- `isBasedOn` entries come back as proper `KGXKnowledgeSource` objects already — no extra step
  needed there.
- **Schema data has no ORION parser either way.** `KGXSchema` (the class that produces
  `schema.json`) only has `to_json()`, not `from_dict()`. Read schema data as a plain dict and
  access `schema["nodes"]`/`schema["edges"]`/`schema["nodes_summary"]`/`schema["edges_summary"]`
  directly.
- Map results into the dashboard's own internal representation at the loader boundary (see
  "Internal representation" below) rather than passing `KGXGraphMetadata` instances into viz/diff
  code — that keeps the app insulated if ORION restructures these classes independently of the
  on-disk JSON format.

**Import-time risk — resolved, not an open question:** despite the ORION README calling
`ORION_STORAGE`/`ORION_GRAPHS` "required," `Config` defines both as `Optional[str] = None`, so
`pydantic-settings` validates nothing and raises nothing when they're unset. The
`get_storage_dir()`/`get_graphs_dir()` fallback logic (defaults to `~/ORION-workspace/...`) only
runs when those getters are actually called, and `kgx_metadata.py` never calls them. So
`from orion.kgx_metadata import KGXGraphMetadata` works with both env vars unset — no dummy values
or lazy-import workaround needed. Keep a real import smoke test in the test suite anyway (cheap
insurance against a future ORION release changing this).

## graph-metadata.json shape (JSON-LD, `@context` uses schema.org + biolink)

Real examples fetched from `https://robokop.renci.org/graphs/RobokopKG/<version>/graph-metadata.json`
and its linked `schema.json` informed these — not guesses.

- Top-level dataset fields: `name`, `version`, `dateCreated`, `dateModified`, `license`,
  `biolinkVersion`, `babelVersion`, `keywords`, `creator`, `funder`.
- `hasPart`: array of contributing subgraphs, each with `@id`, `name`, `orion:nodeCount`,
  `orion:edgeCount`. **Counts vary by orders of magnitude** across subgraphs in the same graph
  (observed range: 146 to 4.9M nodes) — any bar chart of these needs a log-scale option.
- `isBasedOn`: array of underlying data sources, each with `id` (an `infores:` CURIE), `name`,
  `description`, `license`, `attribution`, `citation` (array), `version`. **Some fields are empty
  strings** in practice (e.g. `"name": ""`) — render defensively.
- `schema`: **shape varies across real releases and must be detected, not assumed** — confirmed
  across three real graphs:
  - RobokopKG: a *pointer* object `{"@id": "...schema.json"}` requiring a second fetch.
  - `translator_kg_open`: **embedded inline** — directly contains `nodes`, `nodes_summary`,
    `edges`, etc., no separate fetch needed.
  - `alliance`: **absent entirely.**
  - The parser must branch explicitly: check whether `data["schema"]` contains `"@id"` (pointer —
    fetch it) or `"nodes"`/`"edges"` directly (inline — use as-is). Not a "handle it later" TODO.
  - Only `graph-metadata.json` is loaded initially; `schema.json` must not be fetched until a
    visualization requiring it is opened. The single-graph overview must render fully and
    gracefully from `graph-metadata.json` alone when schema data is absent or a fetch fails.

## schema.json shape (produced by ORION's `generate_schema()` in `orion/kgx_metadata.py`)

- `schema.nodes`: array of objects, one per `biolink:category` combination (categories reduced to
  Biolink *leaf* categories — redundant parents removed), each with:
  - `count` — total nodes with this category set.
  - `id_prefixes` — dict of identifier prefix → count.
  - `attributes` — dict of attribute name → fill count. **Size is wildly inconsistent across
    categories** (`SequenceVariant` ~4 keys; `SmallMolecule` 1,500+, mostly `CHEBI_ROLE_*` counts
    of 1). Never render unfiltered — top-N by default with search for the rest. **Already sorted
    descending by count** (ORION's `sort_dict_by_values`) — top-N is a slice, not a sort.
- `schema.edges`: array of objects, one per (subject-category, predicate, object-category) triple:
  `subject_category` (list), `predicate` (string), `object_category` (list), `count`,
  `primary_knowledge_sources` (dict, pre-sorted), `qualifiers` (dict, pre-sorted), `attributes`
  (dict, pre-sorted), `subject_id_prefixes`, `object_id_prefixes`. This is the Sankey diagram data
  source. Occasionally `primary_knowledge_sources` contains a `None`/null key — render
  defensively, don't assume every key is a valid CURIE.
- `schema.nodes_summary` / `schema.edges_summary`: **pre-aggregated rollups** —
  `total_count`, aggregated `id_prefixes`/`attributes` (nodes) and aggregated
  `predicates`/`primary_knowledge_sources`/`predicates_by_knowledge_source`/`qualifiers`/
  `attributes` (edges). Use these directly for overview/top-level breakdowns instead of
  re-aggregating from the granular arrays — ORION already did that work.
  `predicates_by_knowledge_source` is a ready-made "predicate composition per source" breakdown,
  rendered as a Sankey (source → predicate) in this app — not a heatmap, stacked bar, or table.

## merge-metadata.json (out of scope for implementation — documented so the shape isn't lost)

Found alongside `translator_kg_open`'s `graph-metadata.json`. Not to be parsed or built into UI
this iteration.

- `sources`: dict of `source_id` → `{release_version, "merged_nodes.jsonl": {nodes: N},
  "merged_edges.jsonl": {edges: N}}` — per-source raw counts before merging.
- `merging_code_version`, `merged_nodes`, `merged_edges`, `final_node_count`, `final_edge_count`,
  `unmerged_edge_count` — merge-step bookkeeping. A `merged_edges: 0` value is expected when it
  matches `unmerged_edge_count == final_edge_count` (no edges deduplicated), not an anomaly.
- `merge_warnings`: `{mismatched_properties: [], dropped_properties: [...]}` — a real QC signal
  not available anywhere else.
- Two deferred ideas, only worth revisiting if this file proves reliably present across releases:
  surfacing `merge_warnings` as a data-quality note, and comparing summed pre-merge counts against
  `final_node_count` as a normalization-collapse metric.

**Implication for the diff module:** any diff over `schema.json` attribute dicts needs to handle
one side having thousands of keys the other side doesn't have at all — treat missing keys as
"count 0," not an error.

## Internal representation (design for schema evolution)

We assume every graph's metadata follows the ORION shape above, but that shape **will evolve**
(ORION ships frequent releases). Don't hard-wire assumptions about this exact shape throughout the
codebase:

- Parse metadata through the `parsers/graph_metadata.py` adapter layer, which turns raw JSON into
  an internal, typed representation the rest of the app (viz, diff) works against — never ORION
  classes or raw JSON keys directly outside this layer.
- This has materialized as `ParsedGraphMetadata` / `GraphSchema` and related dataclasses
  (`NodeCategory`, `EdgeTriple`, `KnowledgeSource`, `SubgraphSource`,
  `KnowledgeSourcePredicateCount`) in `parsers/models.py`. `GraphSchema.raw` retains the plain-dict
  schema payload for the ORION diff boundary (see the `graph-comparison-diff` skill) — new code
  should consume the typed fields, not `raw`, except at that one boundary.
- If practical, tag the internal representation with a detected schema/version marker (e.g. from
  `biolinkVersion`) so a future second parser/adapter can be added for a new shape without
  breaking the old one — prefer "add a new adapter" over "add branching logic into the existing
  one" as the shape drifts.
- The diff module's inputs follow the same rule: it consumes `ParsedGraphMetadata`, never raw
  `graph-metadata.json`/`schema.json`, so a schema change only requires updating the parser.
- ORION imports are lazy and cached with `@lru_cache(maxsize=1)` in `parsers/graph_metadata.py`,
  so importing the app does not initialize ORION/BMT until a parse actually happens.
