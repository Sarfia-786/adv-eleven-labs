import json
import subprocess
import sys
from pathlib import Path

import pytest
from services.hosted_catalog_index import CatalogIndex


def write_manifest(path, items):
    path.write_text(json.dumps({"schema_version": 1, "items": items}), encoding="utf-8")
    return path


def ids(page):
    return [voice.id for voice in page.items]


def test_curated_search_and_combined_exact_filters(tmp_path):
    items = [
        {
            "id": "speaker_A",
            "name": "Straße",
            "description": "Café am Fluss",
            "language": "Deutsch",
            "use_case": "narration",
            "facets": {"gender": "neutral", "accent": "Kölsch", "tone": "Warm"},
        },
        {
            "id": "speaker_B",
            "name": "Strasse",
            "language": "Deutsch",
            "category": "narration",
            "presentation": "neutral",
            "accent": "Kölsch",
            "tone": "warmer",
        },
    ]
    index = CatalogIndex.load(write_manifest(tmp_path / "voices.json", items))
    assert ids(index.search("STRASSE")) == ["speaker_A", "speaker_B"]
    assert ids(index.search("CAFE\u0301")) == ["speaker_A"]
    page = index.search(
        "stras",
        name="STRASSE",
        language="deutsch",
        accent="KO\u0308LSCH",
        presentation="neutral",
        tone="WARM",
        category="NARRATION",
    )
    assert ids(page) == ["speaker_A"]
    assert index.search(tone="war").total == 0
    assert index.search(accent="Kölsch", category="comedy").total == 0
    assert index.get("speaker_A").name == "Straße"
    assert index.get("speaker_a") is None


def test_missing_fields_stay_unknown_even_when_other_text_suggests_them(tmp_path):
    item = {
        "id": "saved_01",
        "name": "The British Whisperer",
        "language": " ",
        "instruct": "british accent",
        "facets": {"lang": "Welsh", "accent": None},
        "audio": {"url": "https://example.invalid/reference.wav"},
    }
    index = CatalogIndex.load(write_manifest(tmp_path / "voices.json", [item]))
    voice = index.get("saved_01")
    assert voice.language == "Welsh"
    assert voice.accent is voice.tone is voice.presentation is None
    assert voice.category is voice.description is voice.license is None
    assert voice.engine_compatibility is voice.preview_provenance is None
    assert index.search(accent="british accent").total == 0
    assert index.search(tone="whisper").total == 0


def test_curated_provenance_and_native_facets(tmp_path):
    items = [
        {
            "id": "v1",
            "presentation": "androgynous",
            "category": "fiction",
            "use_case": "narration",
            "engine_compatibility": ["studio-engine"],
            "preview_provenance": "review-145",
            "type": "preset",
            "facets": {
                "gender": "unspecified",
                "age": "adult",
                "pitch": "low",
                "whisper": False,
            },
        },
        {"id": "v2", "facets": {"whisper": True}},
        {"id": "v3"},
    ]
    index = CatalogIndex.load(write_manifest(tmp_path / "voices.json", items))
    assert ids(
        index.search(
            gender="ANDROGYNOUS",
            category="fiction",
            age="adult",
            pitch="low",
            whisper=False,
        )
    ) == ["v1"]
    assert ids(index.search(whisper=True)) == ["v2"]
    assert index.get("v3").whisper is None
    voice = index.get("v1")
    assert (voice.type, voice.engine_compatibility, voice.preview_provenance) == (
        "preset",
        ("studio-engine",),
        "review-145",
    )


def test_pages_are_stable_across_reordered_manifests(tmp_path):
    items = [
        {"id": "b", "name": "Écho"},
        {"id": "z", "name": "Zulu"},
        {"id": "a", "name": "E\u0301CHO"},
        {"id": "x"},
        {"id": "c", "name": "Écho"},
    ]
    for rows in (items, list(reversed(items))):
        index = CatalogIndex.load(write_manifest(tmp_path / "voices.json", rows))
        pages = [index.search(offset=n, limit=2) for n in (0, 2, 4, 6)]
        assert [ids(page) for page in pages] == [["z", "a"], ["b", "c"], ["x"], []]
        assert all(page.total == 5 for page in pages)
        assert index.search(limit=0).items == ()
        assert index.get("x").name is None


@pytest.mark.parametrize(
    "rows", [[{"id": "same"}, {"id": "same"}], [{"name": "A"}], [{"id": " padded "}]]
)
def test_invalid_or_duplicate_ids_cannot_replace_a_saved_voice(tmp_path, rows):
    with pytest.raises(ValueError, match="id"):
        CatalogIndex.load(write_manifest(tmp_path / "voices.json", rows))


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        {"items": []},
        {"schema_version": True, "items": []},
        {"schema_version": 2, "items": []},
        {"schema_version": 1, "items": {}},
    ],
)
def test_invalid_manifest_rejected(tmp_path, manifest):
    path = tmp_path / "voices.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        CatalogIndex.load(path)


@pytest.mark.parametrize(
    "options",
    [
        {"offset": -1},
        {"limit": -1},
        {"limit": True},
        {"whisper": "false"},
        {"tnoe": "warm"},
    ],
)
def test_invalid_filters_and_pagination_are_rejected(tmp_path, options):
    index = CatalogIndex.load(write_manifest(tmp_path / "voices.json", []))
    with pytest.raises(ValueError):
        index.search(**options)


def test_vendored_manifest_preserves_all_ids_and_declared_metadata():
    manifest = (
        Path(__file__).resolve().parents[1] / "omnivoice-gallery" / "manifest.json"
    )
    items = json.loads(manifest.read_text(encoding="utf-8"))["items"]
    index = CatalogIndex.load()
    assert {row["id"] for row in items} == set(ids(index.search()))
    voice = index.get("feat_00_the_librarian")
    assert (
        voice.name,
        voice.language,
        voice.accent,
        voice.presentation,
        voice.category,
    ) == (
        "The Librarian",
        "English",
        "british accent",
        "female",
        "narration",
    )
    assert voice.tone is None
    recorded = index.get("community_pt_br_thalia")
    assert (recorded.license, recorded.author, recorded.source) == (
        "CC-BY-4.0",
        "iluucasz",
        "community",
    )
    assert recorded.preview_provenance is None


def test_offline_construction_in_fresh_process(tmp_path):
    backend = Path(__file__).resolve().parents[1] / "backend"
    script = """
import sys

def offline(event, args):
    if event.startswith("socket.") or event in {"subprocess.Popen", "os.system"}:
        raise AssertionError(event)
    if event == "import" and args[0].split(".")[0] in {
        "torch", "torchaudio", "transformers", "onnxruntime", "omnivoice"
    }:
        raise AssertionError(args[0])

sys.addaudithook(offline)
sys.path.insert(0, sys.argv[1])
from services.hosted_catalog_index import CatalogIndex
assert CatalogIndex.load().search(language="Portuguese").total > 0
"""
    subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, str(backend)],
        cwd=tmp_path,
        check=True,
    )
