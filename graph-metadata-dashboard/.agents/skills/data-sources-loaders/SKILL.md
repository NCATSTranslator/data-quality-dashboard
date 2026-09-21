---
name: data-sources-loaders
description: MetadataSource loader implementations - file upload, kgx-storage manifest dropdown, and the trusted-URL loader's security model (allow-listed prefixes, private/reserved-host rejection, redirect blocking, streamed size limits). Load before touching loaders/, before adding any new remote-fetch path, or before wiring up a new metadata source.
---

# Data sources & loaders

Data sources for this iteration:

- **File upload** — user provides a `graph-metadata.json` and, optionally, a `schema.json`.
- **kgx-storage manifest dropdown**:
  - `https://kgx-storage.ci.transltr.io/releases/latest-release-summary.json` — top-level
    manifest, one entry per source graph (e.g. `alliance`, `ctd`, `bindingdb`, ...), each with
    `release_version` and a `data` URL pointing at that release's folder. Populates the dropdown.
  - `https://kgx-storage.ci.transltr.io/releases/<source>/latest-release.json` — same shape,
    scoped to one source; useful to re-check a single graph's latest release without re-fetching
    the full summary.
  - The actual metadata file is at `<data>/graph-metadata.json` (e.g.
    `.../releases/alliance/2026_06_09/graph-metadata.json`). **`schema.json` is not always present
    at that path** — treat it as optional, never assume it exists alongside `graph-metadata.json`.
  - These manifests only expose the **latest** release per source. Enumerating prior releases
    (needed for a future deployment-history dashboard, not this one) is out of scope.
- **Trusted URL input** — supported only through the existing URL loader security model in
  `loaders/url.py`: `REMOTE_METADATA_ALLOWED_URL_PREFIXES`, private/reserved host rejection,
  redirect blocking, streamed size limits, and JSON-object validation. **Do not bypass these
  guards or introduce a second URL-fetch path.** Any new remote-fetch path (including whatever
  future work needs) must go through the same guards.

Build the source-of-metadata concept as a small interface (`MetadataSource` protocol with
`UploadedFile` and `KgxStorageRelease` implementations) so a future `RetrieverAPI` source can be
added without touching visualization or diff code. Retriever-API integration itself is
out of scope for this iteration — the loader abstraction just needs to make it easy to add later.
