"""Check trusted PR workflows, the sample ruleset and the archived agreements."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[1]
_WORKFLOWS = _REPO / ".github" / "workflows"
# Triggers that run with a write token and repository secrets, even on fork PRs.
_PRIVILEGED_TRIGGERS = {"pull_request_target", "issue_comment", "workflow_run"}
# SHA-256 of each published agreement with LF line endings. Never update a hash:
# publish a new version file instead, so existing signatures keep their text.
_PUBLISHED_AGREEMENTS = {
    ".github/CLA-1.0.md": "b21cab097b9ea9b7f9d938724910276bd1253083800f42d5e176c9d335086b84",
    ".github/CCLA-1.0.md": "4207f055243a9c4c87f89dcb1de49e61b46ffb1605ae020e848709c8705c9d5c",
}


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    # PyYAML reads the bare `on:` key as boolean True.
    data["on"] = data.pop(True, data.get("on")) or {}
    return data


def _triggers(workflow: dict) -> set[str]:
    on = workflow["on"]
    return set(on) if isinstance(on, (dict, list)) else {on}


def test_published_agreements_are_never_edited():
    for path, expected in _PUBLISHED_AGREEMENTS.items():
        text = (_REPO / path).read_text(encoding="utf-8").replace("\r\n", "\n")
        assert hashlib.sha256(text.encode()).hexdigest() == expected, (
            f"{path} changed. Publish the new terms as a new version file instead."
        )


def test_privileged_workflows_never_run_pull_request_code():
    """Allow privileged checkouts to use only the trusted event base commit."""
    for path in sorted(_WORKFLOWS.glob("*.y*ml")):
        workflow = _load(path)
        if not _triggers(workflow) & _PRIVILEGED_TRIGGERS:
            continue
        text = path.read_text(encoding="utf-8")
        assert "pull_request.head" not in text and "head_sha" not in text, f"{path.name} references PR head code"
        for name, job in (workflow.get("jobs") or {}).items():
            where = f"{path.name}:{name}"
            assert "uses" not in job, f"{where} calls a reusable workflow"
            for step in job.get("steps", []):
                uses = step.get("uses", "")
                assert not uses.startswith("actions/download-artifact@"), f"{where} downloads artifacts"
                if uses.startswith("actions/checkout@"):
                    options = step.get("with") or {}
                    assert "repository" not in options, f"{where} checks out another repository"
                    assert options.get("ref", "${{ github.sha }}") in {
                        "${{ github.sha }}",
                        "${{ github.event.pull_request.base.sha }}",
                    }, f"{where} checks out a non-base ref"
                    assert options.get("persist-credentials") is False, f"{where} keeps credentials"
                assert "${{ github.event" not in str(step.get("run", "")), f"{where} interpolates event data"


def _main_ruleset() -> dict:
    text = (_REPO / "docs" / "maintainers" / "repository-settings.md").read_text(encoding="utf-8")
    blocks = [json.loads(b) for b in re.findall(r"<<'JSON'\n(.*?)\nJSON\n", text, re.DOTALL)]
    return next(b for b in blocks if b.get("name") == "main")


def test_main_ruleset_requires_pull_requests_and_commit_identities():
    rules = {rule["type"]: rule.get("parameters", {}) for rule in _main_ruleset()["rules"]}
    # Required checks alone accept a direct push whose commit already passed.
    assert rules["pull_request"] == {
        "required_approving_review_count": 0, "dismiss_stale_reviews_on_push": False,
        "require_code_owner_review": False, "require_last_push_approval": False,
        "required_review_thread_resolution": False,
    }
    contexts = {c["context"] for c in rules["required_status_checks"]["required_status_checks"]}
    assert "Tests (backend + frontend)" in contexts
    assert contexts.isdisjoint({"CLA", "CLA gate"})
    identity_job = next(iter(_load(_WORKFLOWS / "commit-identity.yml")["jobs"].values()))["name"]
    assert identity_job in contexts
    assert "Commit identity policy" in contexts  # fork jobs cannot forge this privileged status
    assert {"deletion", "non_fast_forward"} <= set(rules)


def test_identity_check_and_secret_scan_run_for_all_pull_requests():
    for job in _load(_WORKFLOWS / "commit-identity.yml")["jobs"].values():
        assert "ci_scope" not in str(job.get("steps")) and "draft" not in str(job.get("if", ""))
    secrets = _load(_WORKFLOWS / "security.yml")["jobs"]["secrets"]
    assert "needs" not in secrets and "if" not in secrets


def test_review_bots_skip_drafts():
    coderabbit = yaml.safe_load((_REPO / ".coderabbit.yaml").read_text(encoding="utf-8"))
    assert coderabbit["reviews"]["auto_review"]["drafts"] is False
    greptile = json.loads((_REPO / "greptile.json").read_text(encoding="utf-8"))
    assert greptile["triggerOnDrafts"] is False
