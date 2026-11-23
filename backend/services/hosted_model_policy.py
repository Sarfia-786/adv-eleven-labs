"""Offline, fail-closed gate for paid hosted model inference.

Local licence acknowledgements do not grant hosted inference permission.
Workers pass the exact selected revision and actual local artifact directories.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from services import model_licenses

HOSTED_REVIEW_SCOPE = "hosted_paid_inference_and_outputs"


class HostedModelDenied(RuntimeError):
    """Non-retryable legal/inventory denial, not an engine failure."""

    code = "hosted_model_not_permitted"

    def __init__(self, blockers: list[str]):
        self.blockers = sorted(set(blockers))
        super().__init__(self.code)

    def detail(self) -> dict:
        return {"code": self.code, "blockers": self.blockers}


def _dependencies(catalogue: list[dict], identity: str) -> tuple[set[str], set[str]]:
    entries = [m for m in catalogue if isinstance(m, dict)
               and (m.get("id") or m.get("repo_id")) == identity]
    if len(entries) > 1:
        raise ValueError("ambiguous catalogue selection")
    if not entries:
        return set(), set()
    entry = entries[0]
    required_files = set()
    for field in ("required_files", "config_required_files", "known_files"):
        files = entry.get(field) or []
        if not isinstance(files, list) or any(not isinstance(x, str) for x in files):
            raise ValueError("invalid catalogue required files")
        required_files.update(files)
    dependencies = set()

    def walk(spec: dict) -> None:
        children = spec.get("dependencies", [])
        if not isinstance(children, list):
            raise ValueError("invalid catalogue dependencies")
        for item in children:
            if not isinstance(item, dict) or not isinstance(item.get("repo_id"), str):
                raise ValueError("invalid catalogue dependency")
            dependencies.add(item["repo_id"])
            walk(item)

    walk(entry)
    return dependencies, required_files


def _review_blockers(row: dict) -> list[str]:
    blockers = model_licenses.record_blockers(row)
    if row.get("review_status") != "cleared" or row.get("commercial_use") is not True:
        blockers.append("commercial_review_missing")
    if row.get("commercial_inference") != "permitted":
        blockers.append("commercial_inference_not_permitted")
    if row.get("commercial_outputs") != "permitted":
        blockers.append("commercial_outputs_not_permitted")
    if row.get("review_scope") != HOSTED_REVIEW_SCOPE:
        blockers.append("hosted_review_scope_missing")
    if not isinstance(row.get("reviewed_by"), str) or not row["reviewed_by"].strip():
        blockers.append("reviewer_missing")
    try:
        if not isinstance(row.get("reviewed_at"), str):
            raise ValueError("missing date")
        date.fromisoformat(row["reviewed_at"])
    except ValueError:
        blockers.append("review_date_missing")
    if model_licenses.license_category(row) not in {"commercial", "conditions"}:
        blockers.append("license_restricted_or_unknown")
    if row.get("variants"):
        blockers.append("variant_provenance_unverified")
    deps = row.get("required_components")
    if (not isinstance(deps, list)
            or any(not isinstance(d, str) or not d for d in deps)
            or len(set(deps)) != len(deps)):
        blockers.append("component_closure_incomplete")
    if not all(isinstance(row.get(k), str) and row[k].strip()
               for k in ("license", "credit", "source_url", "evidence_url")):
        blockers.append("attribution_or_source_missing")
    try:
        model_licenses._component(row)
    except (model_licenses.ModelTermsError, KeyError, TypeError, ValueError):
        blockers.append("artifact_or_terms_evidence_invalid")
    return blockers


def evaluate_paid_inference(
    model_id: str, revision: str, components: list[dict], *,
    registry: dict | None = None, catalogue: list[dict] | None = None,
) -> dict:
    """Offline decision; components are exact {id,revision,root} entries.

    This hashes every reviewed artifact. Hold snapshots immutable during inference.
    A preflight or local notice receipt is never a reusable authorization token.
    """
    blockers: list[str] = []
    try:
        source = registry if registry is not None else model_licenses.load_registry()
        if (not isinstance(source, dict) or source.get("schema_version") != 2
                or source.get("data_kind", "production") != "production"
                or not isinstance(source.get("models"), list)):
            raise ValueError("invalid registry")
        rows = {}
        for row in source["models"]:
            if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                    or row["id"].casefold() in rows
                    or row.get("data_kind", "production") != "production"):
                raise ValueError("invalid row")
            rows[row["id"].casefold()] = row
        if catalogue is None:
            from services.model_catalogue import KNOWN_MODELS
            catalogue = KNOWN_MODELS
        if not isinstance(catalogue, list):
            raise ValueError("invalid catalogue")
    except (OSError, ValueError, TypeError, model_licenses.ModelTermsError):
        return {"allowed": False, "model_id": model_id, "revision": revision,
                "components_checked": [], "blockers": ["registry_unavailable_or_invalid"]}

    actual = {}
    if not isinstance(components, list) or not components:
        blockers.append("runtime_components_missing")
    else:
        for component in components:
            if (not isinstance(component, dict)
                    or set(component) != {"id", "revision", "root"}
                    or any(not isinstance(component.get(k), str) or not component[k]
                           for k in ("id", "revision", "root"))):
                blockers.append("runtime_component_invalid")
                continue
            key = component["id"].casefold()
            if key in actual:
                blockers.append("runtime_component_duplicate")
            actual[key] = component
    if (not isinstance(model_id, str) or not model_id
            or not isinstance(revision, str)
            or not model_licenses._SHA.fullmatch(revision)):
        blockers.append("runtime_revision_unverified")
    root_id = model_id.casefold() if isinstance(model_id, str) else ""
    if root_id not in actual:
        blockers.append("selected_model_missing")
    elif actual[root_id]["revision"] != revision:
        blockers.append("selected_model_revision_mismatch")
    expected: set[str] = set()
    visiting: set[str] = set()

    def visit(identity: str) -> None:
        key = identity.casefold()
        if key in visiting:
            blockers.append("component_dependency_cycle")
            return
        if key in expected:
            return
        expected.add(key)
        row = rows.get(key)
        if row is None:
            blockers.append(f"{identity}:record_missing")
            return
        visiting.add(key)
        blockers.extend(f"{row['id']}:{reason}" for reason in _review_blockers(row))
        deps = row.get("required_components")
        if isinstance(deps, list):
            for dep in deps:
                if isinstance(dep, str) and dep:
                    visit(dep)
        try:
            catalog_deps, required_files = _dependencies(catalogue, row["id"])
            manifest = row.get("artifacts")
            paths = {a.get("path") for a in manifest if isinstance(a, dict)} if isinstance(manifest, list) else set()
            if not required_files.issubset(paths):
                blockers.append(f"{row['id']}:required_files_unreviewed")
            for dep in catalog_deps:
                visit(dep)
        except (ValueError, TypeError, RecursionError):
            blockers.append("catalogue_dependencies_unverified")
        visiting.remove(key)

    if root_id:
        visit(model_id)
    if set(actual) != expected:
        blockers.append("runtime_component_set_mismatch")
    for key in sorted(expected & set(actual)):
        row, item = rows.get(key), actual[key]
        if row is None:
            continue
        rev = item["revision"]
        if (not model_licenses._SHA.fullmatch(rev)
                or rev != row.get("revision") or rev != row.get("runtime_revision")):
            blockers.append(f"{row['id']}:runtime_revision_mismatch")
            continue
        root = Path(item["root"])
        if not root.is_absolute() or not root.is_dir():
            blockers.append(f"{row['id']}:artifact_root_unavailable")
            continue
        artifacts = row.get("artifacts")
        for artifact in artifacts if isinstance(artifacts, list) else []:
            if not isinstance(artifact, dict) or not model_licenses.safe_file(artifact.get("path")):
                blockers.append(f"{row['id']}:artifact_manifest_unverified")
                continue
            path = root / artifact["path"]
            try:
                if (not path.is_file() or path.stat().st_size != artifact["size_bytes"]
                        or model_licenses.file_digest(path) != artifact["sha256"]):
                    blockers.append(f"{row['id']}:artifact_integrity_failed")
            except (OSError, KeyError, ValueError, TypeError):
                blockers.append(f"{row['id']}:artifact_integrity_failed")
    return {"allowed": not blockers, "model_id": model_id, "revision": revision,
            "components_checked": sorted(actual), "blockers": sorted(set(blockers))}


def require_paid_inference(
    model_id: str, revision: str, components: list[dict], *,
    registry: dict | None = None, catalogue: list[dict] | None = None,
) -> dict:
    """Worker entry point: invoke before any paid inference."""
    result = evaluate_paid_inference(model_id, revision, components,
                                     registry=registry, catalogue=catalogue)
    if not result["allowed"]:
        raise HostedModelDenied(result["blockers"])
    return result


def preflight_deployment(
    manifest: dict, *, registry: dict | None = None,
    catalogue: list[dict] | None = None,
) -> dict:
    """Evaluate all declared deployment selections offline; no side effects."""
    if (not isinstance(manifest, dict) or set(manifest) != {"schema_version", "models"}
            or manifest["schema_version"] != 1 or not isinstance(manifest["models"], list)
            or not manifest["models"]):
        return {"allowed": False, "blockers": ["deployment_manifest_invalid"], "models": []}
    findings = []
    seen = set()
    for model in manifest["models"]:
        if not isinstance(model, dict) or set(model) != {"model_id", "revision", "components"}:
            return {"allowed": False, "blockers": ["deployment_manifest_invalid"], "models": []}
        identity = model["model_id"]
        if not isinstance(identity, str) or identity.casefold() in seen:
            return {"allowed": False, "blockers": ["deployment_manifest_invalid"], "models": []}
        seen.add(identity.casefold())
        findings.append(evaluate_paid_inference(
            model["model_id"], model["revision"], model["components"],
            registry=registry, catalogue=catalogue))
    return {"allowed": all(x["allowed"] for x in findings),
            "blockers": sorted(set(b for x in findings for b in x["blockers"])),
            "models": findings}
