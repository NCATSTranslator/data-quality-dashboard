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

## Deployment note

If `diskcache` is in use, its storage path must be a container-writable directory (ideally
configurable via env var), since the default container filesystem is ephemeral — that's fine for a
cache (data is disposable), just don't assume it persists across restarts or replicas. See the
`deployment-packaging` skill for the rest of the container/env-var configuration story.
