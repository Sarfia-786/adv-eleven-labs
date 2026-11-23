# Curated voice catalog index

`services.hosted_catalog_index.CatalogIndex.load()` reads the local
`omnivoice-gallery/manifest.json`. Pass a path to read another UTF-8 gallery
manifest with `schema_version` equal to `1` and an `items` array. Load once
and reuse the snapshot for searches. Load it again after updating the file.

From the repository root, this prints matching names and their saved IDs.

```sh
PYTHONPATH=backend python - <<'PY'
from services.hosted_catalog_index import CatalogIndex

index = CatalogIndex.load()
page = index.search("librarian", language="English", category="narration", limit=10)
for voice in page.items:
    print(voice.id, voice.name)
PY
```

`index.get(id)` resolves the original case-sensitive ID, returning `None`
for an unknown ID. Missing, malformed or duplicate IDs reject the manifest.
Display names can repeat. Pages sort by Unicode-normalized, case-folded
display name, then by ID. Unnamed entries sort last. `offset` and `limit`
are non-negative integers. `page.total` counts all matches before slicing.

Search matches substrings in the ID, description, author and text facets.
Exact filters combine with AND and use the same Unicode normalization as
search. The text filters are `name`, `language`, `accent`, `presentation`
(alias `gender`), `tone`, `category`, `age` and `pitch`. The `whisper`
filter takes a boolean. An entry with an unknown value cannot match that filter.

| Catalog field | Curated input |
| --- | --- |
| ID, name, type, description | Corresponding item fields |
| Language | `language`, then `facets.language` or `facets.lang` |
| Presentation | Explicit `presentation`, falling back to curated `gender` |
| Category | Explicit `category`, falling back to `use_case` |
| Accent, tone, age, pitch, whisper | Corresponding item or `facets` field |
| Attribution | `source`, `author`, `submission` and `license` |
| Engine compatibility, preview provenance | Optional `engine_compatibility` list of engine names and `preview_provenance` text |

An explicit item facet takes precedence over its nested equivalent. Absent
metadata is `None`. The index reads declarations only. For example, a
recorded voice can have an audio URL and an unknown preview provenance.
Hosted access and preview delivery are tracked in issue #11.
