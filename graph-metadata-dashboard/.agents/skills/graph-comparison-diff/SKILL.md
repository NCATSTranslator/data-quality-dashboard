---
name: graph-comparison-diff
description: Diff/comparison scope and design - what to compare, ORION's diff_schemas() boundary, the N-way (2+) comparison strategy, and the plain-Python diff/ module contract. Load before touching diff/, before adding any comparison visualization or summary view, or before changing how multiple selected graphs are compared.
---

# Graph comparison & diff module

## Scope (MVP)

When two graphs are selected, compute and display:

- Total node/edge counts and deltas.
- Graph-level metadata differences that matter to users: graph name, release/version,
  `dateCreated`, `dateModified`, license, Biolink version, Babel version.
- Added/removed data sources (`isBasedOn`) and version changes for sources present in both.
- Subgraph/source contribution differences from `hasPart` when present.
- Schema-level diffs when both graphs have schema:
  - node category count deltas,
  - edge triple count deltas,
  - node `id_prefixes` and `attributes` drift,
  - edge predicates, primary knowledge sources, qualifiers, attributes, and ID-prefix drift.

If either graph has no schema, graph-level/source-level comparison should still render and
schema-specific sections should show a clear unavailable message.

## ORION boundary

Use `from orion import diff_schemas` for schema-level diffs instead of reimplementing the schema
diff algorithm — available in `robokop-orion==2.0.5`. Pass graph-metadata-shaped documents into
ORION, not dashboard-parsed node/edge structures. If a graph has inline schema, pass its raw
`graph-metadata.json` document directly. If the graph metadata references an external schema,
build a graph-metadata-shaped document by inlining the loaded schema under the `schema` key before
calling ORION. Do not call `diff_schemas()` on dashboard-derived typed rows.

Output shape: top-level `old`, `new`, `diff` keys; `diff` contains `nodes`, `nodes_summary`,
`edges`, `edges_summary`. Count diffs use `{old, new, delta, percent_change}`; map diffs use
`{added, removed, changed}`, with `changed` entries carrying count-diff objects. ORION schema
diffs include edge-source count deltas through `edges_summary.primary_knowledge_sources` and
`edges_summary.predicates_by_knowledge_source`; there is no equivalent node-source dimension in
`nodes_summary`. This module compares KGX schema content only, not all graph-level metadata fields
— dashboard code still has to compare graph-level metadata and `isBasedOn` sources itself (see
Scope above).

Do not pass ORION objects or raw graph metadata throughout the app. The dashboard-owned comparison
module (`src/graph_metadata_dashboard/diff/comparison.py`) consumes `ParsedGraphMetadata` objects,
calls ORION only at this one schema-diff boundary, and returns typed dashboard-owned result
objects / simple structured dicts for Dash callbacks to render. No Dash/Flask imports in this
module — it must be callable both from a Dash callback and, later, from an automated QC script.

## N-way (2+ graphs) strategy

For two selected graphs, compare graph A to graph B directly. **For three or more**, use a simple,
understandable pattern rather than a dense all-pairs diff: either use the first selected graph as
the baseline and compare every other selected graph to it, or render matrix-style summary tables
for totals/source presence/category counts. Avoid rendering all edge triples or all attribute keys
without top-N, search, pagination, or drill-down — the ROBOKOP-scale cardinality caution from the
`single-graph-visualizations` skill applies here too, compounded across N graphs.

Entrypoint: `compare(graphs: list[ParsedGraphMetadata]) -> ComparisonResult`, taking a list rather
than a fixed pair, since the app already supports 2+ selected graphs. Keep the pure-Python
comparison inputs generic enough that finer-grained comparisons (e.g. a graph vs. a subset of its
own `hasPart` sources) aren't precluded later, even though that's out of scope for now — comparison
is scoped to independent top-level graphs for this iteration.

## UI wiring

UI mode is derived implicitly from how many graphs are loaded — 0 loaded: empty state; 1 loaded:
single-graph overview/visualizations; 2+ loaded: comparison. **No top-level mode buttons.**
Preserve this model when building out new comparison views rather than reintroducing explicit mode
switching.

Dash routing follows the pattern already in use: `pages/` holds only Dash-auto-discovered route
pages; non-page helper code lives in `components/`. Page modules expose `register_callbacks(...)`
(called with app-scoped `MetadataCache`/loader instances) rather than relying on module-level
`@callback`, and `@app.callback` is used intentionally inside that function so callbacks can close
over those dependencies. `components/comparison.py` is the existing home for comparison-view
components — follow its established structure when adding new summary visualizations rather than
starting a new pattern.

When building new comparison summary visualizations, also load the `dataviz` skill for chart/
color/layout guidance, and `single-graph-visualizations` for the cardinality-handling patterns
(top-N + search, log scale, "Other" bucket) that apply equally on the comparison side.
