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

If users need a downloadable schema diff, export the raw `diff_schemas()` output already attached
to each `SchemaDiffSummary`, wrapped only with per-comparison baseline/target graph metadata to
identify each comparison. Do not reconstruct the ORION diff from dashboard tables, and do not place
the raw diff payload in `dcc.Store`; build the download from server-side cached metadata on demand.
If users need a readable comparison report, prefer a self-contained static HTML file generated from
the existing `ComparisonResult` over PDF/headless-browser rendering. Keep it dependency-free and
non-interactive: a shareable snapshot of the overview, heatmap, and schema summary tables.

## N-way (2+ graphs) strategy

For two selected graphs, compare graph A to graph B directly. **For three or more**, use a simple,
understandable baseline comparison rather than a dense all-pairs diff: use the first selected
graph by default, honor the baseline selector, and compare every other graph against it. Use tables
for totals/source presence/category counts. Avoid rendering all edge triples or all attribute keys
without top-N, search, pagination, or drill-down — the ROBOKOP-scale cardinality caution from the
`single-graph-visualizations` skill applies here too, compounded across N graphs.

Entrypoint: `compare(graphs: list[ParsedGraphMetadata]) -> ComparisonResult`, taking a list rather
than a fixed pair, since the app already supports 2+ selected graphs. Keep the pure-Python
comparison inputs generic enough that finer-grained comparisons (e.g. a graph vs. a subset of its
own `hasPart` sources) aren't precluded later, even though that's out of scope for now — comparison
is scoped to independent top-level graphs for this iteration.

## Summary visualization guidance

Do not add standalone "Top Movers" or "Breaking Changes" sections by default. Those purposes are
handled in the detailed schema panels: node category / edge triple rows are sorted by impact, and
removed items are visually distinguished in the existing added/removed/changed groups. Avoid
duplicating those same rows in an adjacent summary panel unless users explicitly need a separate
digest.

The remaining useful summary view is a comparison heatmap / impact matrix. This can be useful for
two graphs and becomes more valuable for three or more. It should be cross-cutting rather than
constrained to node or edge sections: candidate rows can include total nodes/edges, source or
subgraph changes, node categories, edge triples, predicates, primary knowledge sources, source-
predicate composition, prefixes, qualifiers, and attributes. Columns should represent each
baseline-vs-target comparison, not all graph pairs.

Heatmap rows must be top-N by change magnitude across all selected comparisons, not render-all.
For two or more baseline-to-target comparison columns (that is, three or more selected graphs),
select global rows first: rows with changes in multiple comparison columns should appear before
pair-specific rows. If fewer than the capped row count are global, fill the remaining slots with
the strongest pair-specific rows using a balanced round-robin across comparison columns; otherwise
one comparison can dominate the row set and make other columns mostly empty. Use existing
`GraphComparison` / `SchemaDiffSummary` outputs only; do not call ORION from Dash components or
introduce a parallel diff algorithm. For each row, preserve enough context to let the user jump to
the detailed table where the literal ORION diff is shown. Use one sequential, non-rainbow color
scale for normalized changes rather than assigning unrelated hues to categories. Direction is
shown separately, so do not use red/blue fills as the primary encoding. Rank and scale intensity
with one shared change score for all statuses: relative change fraction (`abs(delta) / max(old,
new)`) times a square-root-scaled absolute-delta ratio. This keeps added/removed rows comparable
with changed rows without displaying fake 100% values. Display ORION percentage values for changed
counts only. Do not render visual intensity for zero or missing changes.

## Interactive comparison details (resolved)

- Keep the complete typed schema changes in `ComparisonResult`. Do not apply upstream top-25
  truncation: the heatmap and remaining-changes dialogs need candidates beyond the inline lists.
  Heatmap Top items defaults to 20, accepts any positive whole number, and applies on Enter or
  blur with a visible hint. Limit the effective count to available change rows. Warn that large 
  selections may slow rendering; pagination is not needed for now. Invalid inputs fall back to the 
  default. Reuse the cached comparison snapshot when changing the count rather than recomputing 
  the comparison. Preserve the global-first, pair-balanced ranking described above.
- The Comparison Overview puts the chosen baseline first and marks it with bold black
  `(baseline)`. Sources and Subgraphs both open Show changes dialogs: group by Status and show
  Changed Fields for modified records, not as a substitute for Added/Removed status. Preserve
  readable wrapping in both metadata columns. Do not restore the isolated gray subgraph-count
  bar, the redundant inline subgraph source table, or the subgraph filter row.
- Subgraph metadata includes node/edge counts when supplied; missing is not zero. A count present
  in only one graph is a changed field. Keep metadata parsing in the parser adapter.
- `diff/details.py` owns adaptive selection and pagination. Node-category and edge-triple tables
  show 25 rows; summary maps show 25 per status, and nested maps show six per status. Absorb one
  or two extra items rather than adding a button just for those items. Apply limits independently
  to Added/Removed/Changed, keeping small groups visible. Headings count the complete group;
  View remaining changes counts exactly the excluded items.
- Do not render all remaining records in a scrolling modal: thousands of entries froze the UI.
  Load only the requested category/page. Pages normally contain 50 items, with a final remainder
  of one or two folded into the preceding page (52 fits one page; 53 becomes 50+3; 102 is 50+52).
  Hide pagination for one-page results. First/Previous/Next/Last use icons with tooltips and
  accessible names; disable navigation at the corresponding boundaries.
- Aggregate summary cards use largest-first placement into three estimated-height columns.
  Estimate map-card height from the actual per-status adaptive inline rows, plus heading and
  remaining-button overhead, not a single capped total of 25. Keep Node Type and Edge Type
  together at the bottom of the lightest populated column; their small responsive grid places
  them side by side when they fit and stacks them otherwise. Preserve No changes cards. This
  is a lightweight estimate, not browser-measured packing; text wrapping can still leave gaps.
- Keep category, graph pair, and controls in a compact header. Use remaining additions/removals
  when the complete remaining set has one such status; mixed sets retain status labels, even
  when one page happens to contain only one status. Avoid redundant single-status count headings.
- Nested details reuse one shared native dialog and a small parent-history stack. Back/Escape
  restore the parent category and page. Show Close only at the outermost level. A new root
  selection clears history; do not mistake inline row buttons for modal-child navigation.
  Keep the single bounded parent page mounted but hidden while its child is open. Dash partial
  updates replace only the child slot; Back clears that slot and reveals the parent without
  rebuilding or resending its table. Still validate snapshot expiry on Back. Scope pager IDs
  by level so retained parent and child controls cannot collide, and ignore inactive-level
  navigation. Replace both slots on root navigation/error; do not accumulate visited pages or
  place rendered payloads in browser stores.
- Modal callbacks use `cache/comparison.py`'s category/page cache, not full-snapshot reloads or
  new ORION diffs (see `caching-layer`). Keep only identifiers/navigation state in `dcc.Store`.
  Preserve the complete raw ORION JSON download and the bounded static HTML report.
- Regressions should cover real small/merged/ROBOKOP data, adaptive boundaries, exact counts,
  first/last navigation, parent restoration, and bounded rendering/cache reads for large results.

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

When building new comparison summary visualizations, follow the heatmap guidance above and the
existing comparison component visual language. The top-N cardinality-handling patterns from
`single-graph-visualizations` still apply on the comparison side.
