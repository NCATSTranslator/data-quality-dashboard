---
name: caching-layer
description: MetadataCache interface design, session-scoped namespacing, TTL/serialization/error-handling policy, and the DiskCache-to-Redis swap contract. Load before touching cache/, before adding anything that stores or reads metadata payloads server-side, or before deciding where cached state should live.
---

# Caching layer

Metadata must be cached server-side behind a cache abstraction:

- All application code must use `MetadataCache`. Never import `diskcache` or `redis` outside
  `cache/`.
- The cache backend is selected only in `cache/factory.py`.
- Keys must be automatically namespaced by `session_id`.
- Metadata payloads must never be stored in `dcc.Store`. `dcc.Store` is only for small UI state
  (selected graph, active tab, etc.) — never the parsed metadata/schema payloads themselves.
- The initial backend is DiskCache. The abstraction must allow Redis to replace DiskCache later
  without changing application code.
- One place owns TTL policy, serialization, and error handling — not scattered across callers.
- Testability: callback tests can use a trivial in-memory fake of the `MetadataCache` interface,
  no Redis or disk needed in CI.

## Resolved (don't re-litigate)

DiskCache to start, behind an interface, with no shared Translator infra to depend on — this is
settled. The required interface, file layout, and session-ID handling above are fully specified,
not left to implementer discretion.

## Comparison snapshots and detail pages

- `cache/comparison.py` owns comparison caching. Give each rendered comparison an opaque,
  session-scoped token; never use one mutable "active comparison" slot. Overlapping renders and
  other tabs must not invalidate a still-displayed comparison or silently change its baseline.
- Keep the complete `ComparisonResult` for heatmap updates and other full-result consumers.
  Also store `SchemaChangeSource` projections for the fixed top-level schema categories when
  creating the snapshot. These exclude unrelated categories and raw ORION export data.
- Modal callbacks use `load_schema_details()`, not `load_comparison()`. On a cold page, read
  only its category source (or the parent node/edge source for nested details), then use the pure
  `diff/details.py` helpers. Cache the resulting typed page lazily; subsequent visits read that
  page directly. Do not eagerly render/cache all pages or add process-global metadata caches.
- Write the small snapshot index before its payloads. Every detail-page read checks this index;
  pages written later must not remain usable after the snapshot expires. Use the backend's
  existing TTL policy without refreshing snapshot expiry during navigation. Missing/expired
  data should show the reload message, never another comparison's data.
- Keep sorting, adaptive cutoffs, and page slicing in `diff/`, and Dash rendering in components.
  Only token, category/pair/page selection, and parent-navigation history belong in browser
  stores; cached metadata and page payloads remain server-side.
- Test cold reads, page reuse, session isolation, overlapping snapshots, expiry, and missing
  category sources through `MetadataCache`. Include DiskCache serialization coverage and verify
  that modal navigation never reloads the complete multi-graph comparison.

## Deployment note

If `diskcache` is in use, its storage path must be a container-writable directory (ideally
configurable via env var), since the default container filesystem is ephemeral — that's fine for a
cache (data is disposable), just don't assume it persists across restarts or replicas. See the
`deployment-packaging` skill for the rest of the container/env-var configuration story.
