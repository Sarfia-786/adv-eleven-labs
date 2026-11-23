"""Synthetic offline acceptance and denial tests for hosted licensing (#8)."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.hosted_model_policy import (  # noqa: E402
    HOSTED_REVIEW_SCOPE,
    HostedModelDenied,
    evaluate_paid_inference,
    preflight_deployment,
    require_paid_inference,
)


@pytest.fixture
def reviewed(tmp_path):
    rows, components = [], []
    for name, revision, data, deps in [
        ("fixture/tts", "a" * 40, b"fictional-model-weights", ["fixture/vocoder"]),
        ("fixture/vocoder", "b" * 40, b"fictional-vocoder-weights", []),
    ]:
        root = tmp_path / revision
        root.mkdir()
        (root / "weights.bin").write_bytes(data)
        text = "Synthetic reviewed permission to run paid inference and deliver outputs."
        rows.append({
            "id": name, "revision": revision, "runtime_revision": revision,
            "license": "Apache-2.0", "credit": f"Synthetic {name} author",
            "source_url": f"https://example.test/{name}",
            "evidence_url": f"https://example.test/{name}/LICENSE",
            "review_status": "cleared", "commercial_use": True,
            "commercial_inference": "permitted", "commercial_outputs": "permitted",
            "review_scope": HOSTED_REVIEW_SCOPE,
            "reviewed_by": "Synthetic reviewer", "reviewed_at": "2026-11-23",
            "component_closure": "complete", "upstream_access": "not_required",
            "required_components": deps,
            "documents": [{"id": name + ":license", "title": "Synthetic terms",
                           "source_url": f"https://example.test/{name}/LICENSE",
                           "sha256": hashlib.sha256(text.encode()).hexdigest(),
                           "text": text, "redistribution": "permitted",
                           "agreement_required": False}],
            "artifacts": [{"path": "weights.bin",
                           "sha256": hashlib.sha256(data).hexdigest(),
                           "size_bytes": len(data), "document_ids": [name + ":license"]}],
        })
        components.append({"id": name, "revision": revision, "root": str(root)})
    registry = {"schema_version": 2, "data_kind": "production",
                "registry_version": "synthetic-only", "models": rows}
    catalogue = [{"repo_id": "fixture/tts",
                  "dependencies": [{"repo_id": "fixture/vocoder"}],
                  "required_files": ["weights.bin"]}]
    return registry, catalogue, components


def decision(fixture):
    registry, catalogue, components = fixture
    return evaluate_paid_inference("fixture/tts", "a" * 40, components,
                                   registry=registry, catalogue=catalogue)


def test_synthetic_review_approves_for_preflight_and_worker(reviewed):
    registry, catalogue, components = reviewed
    assert decision(reviewed)["allowed"]
    assert require_paid_inference("fixture/tts", "a" * 40, components,
                                  registry=registry, catalogue=catalogue)["allowed"]
    manifest = {"schema_version": 1, "models": [
        {"model_id": "fixture/tts", "revision": "a" * 40, "components": components}]}
    assert preflight_deployment(manifest, registry=registry,
                                catalogue=catalogue)["allowed"]


@pytest.mark.parametrize("field,value,blocker", [
    ("review_status", "unreviewed", "commercial_review_missing"),
    ("commercial_use", False, "commercial_review_missing"),
    ("commercial_inference", "unknown", "commercial_inference_not_permitted"),
    ("commercial_inference", "restricted", "commercial_inference_not_permitted"),
    ("commercial_outputs", "unknown", "commercial_outputs_not_permitted"),
    ("commercial_outputs", "restricted", "commercial_outputs_not_permitted"),
    ("license", "CC-BY-NC-4.0", "license_restricted_or_unknown"),
    ("license", "unknown", "license_restricted_or_unknown"),
    ("review_scope", "desktop-only", "hosted_review_scope_missing"),
    ("reviewed_by", "", "reviewer_missing"),
    ("reviewed_at", "unknown", "review_date_missing"),
    ("component_closure", "incomplete", "component_closure_incomplete"),
    ("upstream_access", "gated", "upstream_access_unverified"),
    ("documents", [], "terms_unverified"),
    ("artifacts", [], "artifact_manifest_unverified"),
    ("runtime_revision", None, "runtime_revision_unverified"),
    ("revision", "c" * 40, "evidence_revision_mismatch"),
])
def test_unreviewed_or_restrictive_records_block(reviewed, field, value, blocker):
    registry, catalogue, components = reviewed
    registry["models"][0][field] = value
    result = decision(reviewed)
    assert not result["allowed"]
    assert any(blocker in reason for reason in result["blockers"])
    with pytest.raises(HostedModelDenied) as exc:
        require_paid_inference("fixture/tts", "a" * 40, components,
                               registry=registry, catalogue=catalogue)
    assert exc.value.detail()["code"] == "hosted_model_not_permitted"


def test_invalid_evidence_document_blocks(reviewed):
    reviewed[0]["models"][0]["documents"][0]["sha256"] = "0" * 64
    assert "artifact_or_terms_evidence_invalid" in str(decision(reviewed)["blockers"])


def test_variant_and_missing_attribution_block(reviewed):
    reviewed[0]["models"][0]["variants"] = [{"id": "unreviewed-variant"}]
    assert "variant_provenance_unverified" in str(decision(reviewed)["blockers"])
    reviewed[0]["models"][0]["credit"] = ""
    assert "attribution_or_source_missing" in str(decision(reviewed)["blockers"])


def test_unknown_or_unpinned_model_denied(reviewed):
    registry, catalogue, components = reviewed
    unknown = evaluate_paid_inference("fixture/missing", "a" * 40, components,
                                      registry=registry, catalogue=catalogue)
    assert not unknown["allowed"]
    assert any("record_missing" in b for b in unknown["blockers"])
    assert not evaluate_paid_inference("fixture/tts", "main", components,
                                       registry=registry, catalogue=catalogue)["allowed"]
    altered = copy.deepcopy(components)
    altered[0]["revision"] = "c" * 40
    assert not evaluate_paid_inference("fixture/tts", "a" * 40, altered,
                                       registry=registry, catalogue=catalogue)["allowed"]


def test_component_closure_denies_missing_extra_and_duplicate(reviewed):
    registry, catalogue, components = reviewed
    extra = {"id": "fixture/extra", "revision": "c" * 40,
             "root": components[0]["root"]}
    for actual in (components[:1], components + [extra], components + [components[0]]):
        assert not evaluate_paid_inference("fixture/tts", "a" * 40, actual,
                                           registry=registry, catalogue=catalogue)["allowed"]


def test_catalogue_dependencies_and_files_are_mandatory(reviewed):
    registry, catalogue, components = reviewed
    registry["models"][0]["required_components"] = []
    assert not evaluate_paid_inference("fixture/tts", "a" * 40, components[:1],
                                       registry=registry, catalogue=catalogue)["allowed"]
    catalogue[0]["required_files"].append("unreviewed.bin")
    assert "required_files_unreviewed" in str(decision(reviewed)["blockers"])


def test_modified_missing_or_wrong_snapshot_denied(reviewed):
    registry, catalogue, components = reviewed
    artifact = Path(components[1]["root"]) / "weights.bin"
    artifact.write_bytes(b"bad")
    assert "artifact_integrity_failed" in str(decision(reviewed)["blockers"])
    artifact.unlink()
    assert not decision(reviewed)["allowed"]
    components[1]["root"] = "relative/path"
    assert "artifact_root_unavailable" in str(decision(reviewed)["blockers"])


def test_local_acknowledgement_cannot_override_hosted_denial(reviewed):
    registry, _, _ = reviewed
    registry["models"][0].update(review_status="unreviewed", commercial_use=False,
                                 local_acknowledged=True, legacy_licence_accepted=True)
    assert not decision(reviewed)["allowed"]


def test_invalid_registry_and_manifest_fail_closed(reviewed):
    registry, catalogue, components = reviewed
    registry["models"].append(copy.deepcopy(registry["models"][0]))
    assert decision(reviewed)["blockers"] == ["registry_unavailable_or_invalid"]
    assert not preflight_deployment({"schema_version": 1, "models": []})["allowed"]
    entry = {"model_id": "fixture/tts", "revision": "a" * 40, "components": components}
    assert not preflight_deployment({"schema_version": 1,
                                    "models": [entry, entry]})["allowed"]


def test_fixture_never_enters_production_registry():
    path = Path(__file__).resolve().parents[1] / "backend/config/model_licenses.json"
    inventory = json.loads(path.read_text(encoding="utf-8"))
    assert not any(m.get("id", "").startswith("fixture/") for m in inventory["models"])


def test_bundled_production_model_is_denied():
    from services import model_licenses
    registry = model_licenses.load_registry()
    first = registry["models"][0]
    revision = first.get("runtime_revision") or "main"
    decision = evaluate_paid_inference(first["id"], revision, [
        {"id": first["id"], "revision": revision, "root": "/nonexistent"}
    ], registry=registry, catalogue=[])
    assert decision["allowed"] is False
    assert decision["blockers"]
