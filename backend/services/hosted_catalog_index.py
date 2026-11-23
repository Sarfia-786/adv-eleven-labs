"""Offline search over the vendored gallery and compatible curated v1 manifests."""

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_MANIFEST = Path(__file__).resolve().parents[2] / "omnivoice-gallery" / "manifest.json"
_ITEM_ID = re.compile(r"[a-zA-Z0-9_-]{1,128}")
_TEXT_FACETS = (
    "name",
    "language",
    "accent",
    "presentation",
    "tone",
    "category",
    "age",
    "pitch",
)


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    return None


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip()).casefold()


@dataclass(frozen=True, slots=True)
class CatalogVoice:
    id: str
    type: str | None
    name: str | None
    description: str | None
    language: str | None
    accent: str | None
    presentation: str | None
    tone: str | None
    category: str | None
    age: str | None
    pitch: str | None
    whisper: bool | None
    source: str | None
    author: str | None
    submission: str | None
    license: str | None
    engine_compatibility: tuple[str, ...] | None
    preview_provenance: str | None


class CatalogFormatError(ValueError):
    """The manifest cannot describe an unambiguous catalog snapshot."""


def _read_voice(item: object) -> CatalogVoice:
    if not isinstance(item, dict):
        raise CatalogFormatError("catalog items must be objects")
    voice_id = item.get("id")
    if not isinstance(voice_id, str) or not _ITEM_ID.fullmatch(voice_id):
        raise CatalogFormatError("catalog item needs a valid gallery id")
    facets = item.get("facets")
    if not isinstance(facets, dict):
        facets = {}

    def facet(name: str) -> str | None:
        return _text(item.get(name)) or _text(facets.get(name))

    engines = item.get("engine_compatibility")
    if engines is not None:
        if not isinstance(engines, list) or not all(
            _text(engine) for engine in engines
        ):
            raise CatalogFormatError(
                f"engine_compatibility for {voice_id} must be a list of names"
            )
        engines = tuple(engine.strip() for engine in engines)
    whisper = item.get("whisper", facets.get("whisper"))
    return CatalogVoice(
        id=voice_id,
        type=_text(item.get("type")),
        name=_text(item.get("name")),
        description=_text(item.get("description")),
        language=facet("language") or _text(facets.get("lang")),
        accent=facet("accent"),
        presentation=facet("presentation") or facet("gender"),
        tone=facet("tone"),
        category=facet("category") or _text(item.get("use_case")),
        age=facet("age"),
        pitch=facet("pitch"),
        whisper=whisper if isinstance(whisper, bool) else None,
        source=_text(item.get("source")),
        author=_text(item.get("author")),
        submission=_text(item.get("submission")),
        license=_text(item.get("license")),
        engine_compatibility=engines,
        preview_provenance=_text(item.get("preview_provenance")),
    )


@dataclass(frozen=True, slots=True)
class CatalogPage:
    items: tuple[CatalogVoice, ...]
    total: int


class CatalogIndex:
    """A snapshot ordered by folded display name, then the original, case-sensitive ID."""

    def __init__(self, voices: Iterable[CatalogVoice]):
        self._by_id: dict[str, CatalogVoice] = {}
        self._by_facet: dict[tuple[str, str | bool], set[str]] = {}
        self._terms: dict[str, tuple[str, ...]] = {}
        for voice in sorted(
            voices, key=lambda v: (v.name is None, _fold(v.name or ""), v.id)
        ):
            if voice.id in self._by_id:
                raise CatalogFormatError(f"duplicate catalog id: {voice.id}")
            self._by_id[voice.id] = voice
            terms = [
                _fold(value)
                for value in (voice.id, voice.description, voice.author)
                if value
            ]
            for field in _TEXT_FACETS:
                value = getattr(voice, field)
                if value is not None:
                    key = _fold(value)
                    self._by_facet.setdefault((field, key), set()).add(voice.id)
                    terms.append(key)
            if voice.whisper is not None:
                self._by_facet.setdefault(("whisper", voice.whisper), set()).add(
                    voice.id
                )
            self._terms[voice.id] = tuple(terms)

    @classmethod
    def load(cls, path: str | Path = _MANIFEST) -> "CatalogIndex":
        """Read one local UTF-8 manifest. An empty v1 items array is a valid catalog."""
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        version = manifest.get("schema_version") if isinstance(manifest, dict) else None
        if type(version) is not int or version != 1:
            raise CatalogFormatError("expected gallery schema_version 1")
        items = manifest.get("items")
        if not isinstance(items, list):
            raise CatalogFormatError("catalog items must be an array")
        return cls(_read_voice(item) for item in items)

    def get(self, voice_id: str) -> CatalogVoice | None:
        return self._by_id.get(voice_id)

    def search(
        self,
        query: str = "",
        *,
        offset: int = 0,
        limit: int | None = None,
        **facets: str | bool,
    ) -> CatalogPage:
        """Combine a Unicode substring query with exact facets. Total is before pagination."""
        if type(offset) is not int or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if limit is not None and (type(limit) is not int or limit < 0):
            raise ValueError("limit must be a non-negative integer")
        groups = []
        for field, value in facets.items():
            if field == "gender":
                field = "presentation"
            if field == "whisper" and isinstance(value, bool):
                key = value
            elif field in _TEXT_FACETS and isinstance(value, str):
                key = _fold(value)
            else:
                raise ValueError(f"unsupported catalog filter or value: {field}")
            groups.append(self._by_facet.get((field, key), set()))

        candidates = set.intersection(*groups) if groups else self._by_id.keys()
        needle = _fold(query)
        matches = [
            voice
            for voice in self._by_id.values()
            if voice.id in candidates
            and (not needle or any(needle in term for term in self._terms[voice.id]))
        ]
        stop = None if limit is None else offset + limit
        return CatalogPage(tuple(matches[offset:stop]), len(matches))
