"""Keep the per-checkpoint audit in sync with the selections exposed by VoiceStudio."""
import collections
import json
import re
import runpy
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs/MODEL_PARAMETERS.md").read_text(encoding="utf-8")
REGISTRY = json.loads((ROOT / "backend/config/model_licenses.json").read_text(encoding="utf-8"))
MOBILE = json.loads((ROOT / "mobile/contract/models.json").read_text(encoding="utf-8"))["models"]


def table_rows(title):
    section = DOC.split(f"## {title}\n", 1)[1].split("\n## ", 1)[0]
    return [row.strip("|").split(" | ") for row in section.splitlines() if row.startswith("| ")]


def row_ids(title):
    return collections.Counter(row[0].strip().strip("`") for row in table_rows(title)[2:])


def test_registered_models_and_dynamic_groups_each_have_one_row():
    assert row_ids("Registered checkpoints") == collections.Counter(m["id"] for m in REGISTRY["models"])
    assert row_ids("Runtime-selected assets") == collections.Counter(m["id"] for m in REGISTRY["dynamic_assets"])
    catalog = yaml.safe_load((ROOT / "backend/config/models.yaml").read_text(encoding="utf-8"))
    assert {model["repo_id"] for model in catalog["models"]} <= row_ids("Registered checkpoints").keys()


def test_mobile_pack_mappings_match_the_manifest():
    rows = table_rows("Mobile selections")[2:]
    found = {row[0].strip().strip("`"): row[1].strip("`") for row in rows}
    assert found == {model["id"]: model["repo"] for model in MOBILE}
    assert len(rows) == len(MOBILE)
    assert set(found.values()) <= row_ids("Registered checkpoints").keys()


def test_provider_defaults_match_the_registry():
    from services.llm_providers import all_providers

    rows = table_rows("Translation providers and local servers")[2:]
    found = {}
    for provider_ids, default, _parameters in rows:
        value = re.fullmatch(r"`([^`]+)`", default)
        for provider in provider_ids.strip().split(", "):
            assert provider not in found
            found[provider] = value.group(1) if value else ""
    assert found == {p.id: p.default_model for p in all_providers()}

def test_workflow_selects_registered_inference_groups():
    audit = runpy.run_path(str(ROOT / ".github/scripts/model_cpu_inference.py"))
    groups = audit["groups"]()
    job = yaml.safe_load((ROOT / ".github/workflows/model-cpu.yml").read_text())["jobs"]["model-cpu"]
    assert set(job["strategy"]["matrix"]["group"]) == groups.keys()
    selected = [repo for repos in groups.values() for repo in repos]
    expected = [row["id"] for row in REGISTRY["models"] if
                {"sherpa-onnx-asr", "faster-whisper", "kittentts"}.intersection(row["engines"])]
    assert collections.Counter(selected) == collections.Counter(expected)


@pytest.mark.parametrize("chinese", [True, False])
def test_real_model_smoke_rejects_an_empty_transcript(chinese):
    audit = runpy.run_path(str(ROOT / ".github/scripts/model_cpu_inference.py"))
    with pytest.raises(ValueError):
        audit["verify_transcript"]("", chinese)
