"""Exercise the hosted contract command from outside the source tree."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_hosted_openapi.py"
BASELINE = ROOT / "docs" / "hosted-openapi.json"
ENTITLEMENTS = "/api/v1/entitlements"
DICTIONARIES = "/api/v1/pronunciation-dictionaries"


def run_export(directory, *args, seed="1"):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=directory,
        check=False,
        env={
            **os.environ,
            "PYTHONHASHSEED": seed,
            "VOICE_API_PUBLIC_KEY_FILE": str(directory / "missing-production-key"),
            "VOICE_API_DATABASE_URL": "invalid-database",
            "VOICE_ARTIFACT_BACKEND": "invalid-storage",
        },
        capture_output=True,
    )


def test_same_bytes_from_two_clean_directories(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    stdout = run_export(first)
    output = run_export(second, "--output", "contract.json", seed="42")
    assert stdout.returncode == 0, stdout.stderr.decode()
    assert output.returncode == 0, output.stderr.decode()
    assert stdout.stdout == (second / "contract.json").read_bytes()
    assert list(first.iterdir()) == []
    assert sorted(p.name for p in second.iterdir()) == ["contract.json"]
    check = run_export(second, "--check")
    assert check.returncode == 0, check.stderr.decode()


def test_published_contract_describes_the_real_hosted_routes():
    schema = json.loads(BASELINE.read_bytes())
    operation = schema["paths"][ENTITLEMENTS]["get"]
    assert operation["security"] == [{"Repo1ServiceToken": []}]
    scheme = schema["components"]["securitySchemes"]["Repo1ServiceToken"]
    assert (scheme["type"], scheme["scheme"]) == ("http", "bearer")
    success = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert success["$ref"] == "#/components/schemas/Entitlements"
    body = schema["paths"][DICTIONARIES]["post"]["requestBody"]
    assert body["required"]
    model = body["content"]["application/json"]["schema"]["$ref"].split("/")[-1]
    assert {"entries", "name"} <= set(
        schema["components"]["schemas"][model]["required"]
    )
    assert all(path.startswith("/api/v1/") for path in schema["paths"])


@pytest.mark.parametrize(
    ("change", "needle"),
    [
        ("removed operation", '"get": {'),
        ("newly required request field", '"entries"'),
        ("removed authentication", '"Repo1ServiceToken": []'),
    ],
)
def test_check_reports_contract_changes(change, needle, monkeypatch, capsys, tmp_path):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    import export_hosted_openapi as exporter

    schema = json.loads(BASELINE.read_bytes())
    previous = BASELINE
    if change == "removed operation":
        del schema["paths"][ENTITLEMENTS]["get"]
    elif change == "newly required request field":
        old = json.loads(BASELINE.read_bytes())
        old["components"]["schemas"]["DictionaryInput"]["required"].remove("entries")
        previous = tmp_path / "previous.json"
        previous.write_text(
            json.dumps(old, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    else:
        schema["paths"][ENTITLEMENTS]["get"]["security"] = []
    monkeypatch.setattr(exporter, "build_schema", lambda: schema)
    assert exporter.main(["--check", str(previous)]) == 1
    changes = capsys.readouterr().err.splitlines()
    assert any(line.startswith(("+", "-")) and needle in line for line in changes)


def test_missing_baseline_is_an_actionable_error(tmp_path):
    path = tmp_path / "missing.json"
    result = run_export(tmp_path, "--check", str(path))
    assert result.returncode == 1
    assert path.name.encode() in result.stderr
    assert b"Traceback" not in result.stderr
    assert not path.exists()
