# AGENTS.md — Translator Graph Metadata Dashboard

## What this project is

A Dash (Plotly) web app for **visualizing knowledge graph metadata** produced by
[ORION](https://github.com/RobokopU24/ORION) for the Biomedical Data Translator project, and for
**comparing metadata between two or more graphs**. It reads pre-computed metadata JSON files — it
never touches the graphs themselves (no Neo4j, no KGX node/edge files, no full graph topology).

**Must handle two very different scales of graph.** Individual Data Translator source graphs
(e.g. `alliance`, `ctd`, `bindingdb`) are single-source and comparatively small. **ROBOKOP KG is a
merged graph of ~30 sources** and is much bigger and more structurally complex (millions of nodes,
tens of millions of edges in some subgraphs, attribute dictionaries with 1,500+ keys for some
categories). Do not design or test against only the small case. **Any list/table/chart of nodes,
attributes, or predicates needs a top-N-plus-search or pagination pattern by default, not "render
everything."** This applies to comparison summary views too, not just single-graph ones.

Two workflows only, for this iteration: (1) single graph view — pick or upload a graph's metadata,
see a readable summary; (2) graph comparison — pick 2+ graphs, see what differs between them.
Everything else (deployment tracking, retriever-API polling, persistent history across
deployments) is out of scope — see "Non-goals" below.

This app will be transferred to an umbrella repository
(https://github.com/NCATSTranslator/data-quality-dashboard) that may host other dashboard apps
(e.g. deployment-related). Keep code structured with that in mind.

## Engineering principles

When multiple implementations satisfy this document, in priority order: (1) correctness,
(2) simpler code over clever code, (3) minimize dependencies, (4) minimize architectural
complexity, (5) avoid speculative extensibility unless explicitly required. If implementation
details are uncertain, follow the architecture and constraints in this document and its skills
rather than inventing new patterns.

## Implementation order

Phase 1: project skeleton, loader abstraction, parser layer, cache layer.
Phase 2: single-graph overview, core visualizations.
Phase 3: drill-down visualizations, Sankey diagram.
Phase 4: graph comparison using the ORION schema diff module (`robokop-orion==2.0.5`).

Do not implement later phases before earlier phases are complete.

## Architecture (hard constraints)

- **Dash only.** No FastAPI, no second HTTP framework/process. If a task seems to need one, stop
  and flag it instead of adding it — Dash callbacks are the whole interface.
- **No database, no auth, no persistence across sessions.** Metadata JSON files are the source of
  truth. State lives in a server-side cache, not a DB.
- **ORION is a pinned dependency** (`robokop-orion==2.0.5`, base package only — no `[robokop]`
  extra). Never float the version. See the `orion-metadata-format` skill before parsing any raw
  metadata/schema JSON.
- **Metadata payloads live in the server-side `MetadataCache`, never in `dcc.Store`.** See the
  `caching-layer` skill before touching `cache/`.
- **Comparison/diff logic is plain Python, no Dash imports**, so it's callable from a callback and
  later from an automated QC script. See the `graph-comparison-diff` skill before touching `diff/`.
- **Package boundaries**: `loaders/` (MetadataSource implementations), `parsers/` (JSON →
  internal typed representation), `cache/` (`MetadataCache` interface + backends), `diff/` (pure
  comparison logic), `pages/` (Dash-auto-discovered routes only) and `components/` (Dash layout
  helpers, not routes). A Dash callback calls into `cache/`, `parsers/`, `diff/`, `loaders/` — it
  does not contain parsing, caching, or comparison logic inline.
- **UI mode is implicit** from graph count (0 = empty state, 1 = single-graph view, 2+ =
  comparison) — no top-level mode buttons. Preserve this.
- Remote fetches (kgx-storage loader, trusted-URL loader) go through the existing security guards
  only — no second fetch path. See the `data-sources-loaders` skill.

## Non-goals for this iteration (do not build)

- No database, no ORM, no migrations. No authentication.
- No retriever-API integration (the loader abstraction should make it easy to add later — that's
  the extent of the preparation needed now).
- No deployment-history tracking or persistence across app restarts.
- No FastAPI or any second web framework/process.
- No full KGX graph topology rendering (nodes-and-edges diagrams) — metadata visualization only.

## Coding conventions

- Type hints throughout; the metadata shapes are irregular enough that types catch real bugs.
- Write unit tests for `diff/`, `loaders/`, `parsers/`, and `cache/` independent of Dash. For
  `cache/`, test against the `MetadataCache` interface with a fake in-memory implementation.
- Test fixtures: use three real tiers, not synthetic data — a single-source Translator graph
  (`alliance`), a smaller multi-source merged graph (`translator_kg_open`), and ROBOKOP KG (large,
  multi-source, merged). All three are real, fetchable examples that between them cover the
  pointer/inline/absent `schema` shapes (see the `orion-metadata-format` skill).
- Use `dash.register_page` for single-graph view vs. comparison view rather than one monolithic
  layout with show/hide logic. Page modules expose `register_callbacks(...)` rather than relying
  on module-level `@callback` (see the `graph-comparison-diff` skill for the full pattern).
- Use `uv` for dependency management.
- Before considering a task done, validate with `uv run ruff check .` and `uv run pytest` at
  minimum.

## Skills — load these on demand, not by default

This file only carries constraints that matter on every task. Detailed reference material lives in
`.agents/skills/` (one topic per file, [Agent Skills open standard](https://developers.openai.com/codex/skills)
format) — load the relevant one before working in that area:

| Skill | Load before... |
|---|---|
| `orion-metadata-format` | touching `parsers/`, or reading any raw `graph-metadata.json`/`schema.json` field |
| `caching-layer` | touching `cache/`, or storing/reading any metadata payload |
| `data-sources-loaders` | touching `loaders/`, or adding any remote-fetch path |
| `single-graph-visualizations` | adding/changing a chart or table on the single-graph view |
| `graph-comparison-diff` | touching `diff/`, or adding/changing a comparison visualization |
| `deployment-packaging` | touching `Dockerfile`, `helm/`, or the env-var/entrypoint surface |

These skills also contain the project's "resolved decisions" (settled questions — don't re-ask
them; each skill carries the ones relevant to its area).

`.agents/skills/` is the canonical location (Codex CLI and other Agent-Skills-standard tools read
it natively). `.claude/skills/*` are symlinks into it, purely so Claude Code's own discovery path
also picks them up — edit skill content only under `.agents/skills/`, never the symlinks.
