"""Export or check the hosted Voice API's OpenAPI contract offline."""

import argparse
import difflib
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "hosted-openapi.json"


def build_schema() -> dict:
    """Construct the real application with a temporary verifier and no storage."""
    with TemporaryDirectory() as tmp:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = Path(tmp) / "public.pem"
        public_key.write_bytes(
            key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        settings = {
            "VOICE_API_PUBLIC_KEY_FILE": str(public_key),
            "VOICE_API_ISSUER": "contract-export",
            "VOICE_API_AUDIENCE": "hosted-voice",
            "VOICE_API_SERVICE_ID": "contract-export",
            "VOICE_API_DATABASE_URL": "",
            "VOICE_ARTIFACT_BACKEND": "",
        }
        with (
            patch.dict(os.environ, settings),
            patch.object(sys, "path", [str(ROOT / "backend"), *sys.path]),
        ):
            from hosted_api import create_app

            return create_app().openapi()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--output", type=Path, metavar="FILE", help="write JSON to a file"
    )
    mode.add_argument(
        "--check",
        nargs="?",
        type=Path,
        const=BASELINE,
        metavar="BASELINE",
        help="compare with the published baseline or the specified file",
    )
    args = parser.parse_args(argv)
    rendered = (
        json.dumps(build_schema(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    try:
        if args.check is not None:
            expected = args.check.read_text(encoding="utf-8")
            if rendered == expected:
                return 0
            sys.stderr.writelines(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    rendered.splitlines(keepends=True),
                    fromfile=str(args.check),
                    tofile="generated hosted OpenAPI",
                )
            )
            return 1
        if args.output is None:
            sys.stdout.buffer.write(rendered.encode("utf-8"))
        else:
            args.output.write_bytes(rendered.encode("utf-8"))
    except (OSError, UnicodeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
