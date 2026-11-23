#!/usr/bin/env python3
"""Offline hosted deployment preflight; no network or inference."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from services.hosted_model_policy import preflight_deployment  # noqa: E402
from services.model_licenses import ModelTermsError, read_json  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        manifest = read_json(args.manifest)  # rejects duplicate JSON keys
        result = preflight_deployment(manifest)
    except (OSError, ValueError, ModelTermsError):
        result = {"allowed": False, "blockers": ["deployment_manifest_unreadable"], "models": []}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
