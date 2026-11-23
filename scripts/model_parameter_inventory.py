#!/usr/bin/env python3
"""Offline parameter inventory for every licensed VoiceStudio model source.

This checks metadata, not weight tensors. A family-level published count is
not an exact count of all packaged auxiliary components; unknown remains null.
No network calls, model downloads, torch imports, or accelerator are needed.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WHISPER = "https://github.com/openai/whisper/blob/main/model-card.md"
VOXCPM = "https://huggingface.co/openbmb/VoxCPM2"
KITTEN = "https://huggingface.co/KittenML/kitten-tts-mini-0.8"
POCKET = "https://huggingface.co/kyutai/pocket-tts"

# Rounded, *reported architecture* millions, never fabricated tensor totals.
# For quantized and converted copies, this is the original architecture's
# approximate size; quantization does not reduce the number of parameters.
# Entries with multiple separate networks deliberately remain unknown.
WHISPER_COUNTS = {
    "large-v3": 1550, "large-v2": 1550, "large-v3-turbo": 809,
    "medium": 769, "small": 244, "base": 74, "tiny": 39,
}
COUNTS: dict[str, tuple[int, str, str]] = {}


def record(names: str, millions: int, provenance: str, source: str) -> None:
    for name in names.split():
        if name in COUNTS:
            raise AssertionError(f"duplicate count mapping: {name}")
        COUNTS[name] = (millions, provenance, source)


record(
    "Systran/faster-whisper-large-v3 mlx-community/whisper-large-v3-mlx "
    "openai/whisper-large-v3 Systran/faster-whisper-large-v2",
    1550, "published-family-size", WHISPER,
)
record(
    "mlx-community/whisper-large-v3-turbo openai/whisper-large-v3-turbo "
    "deepdml/faster-whisper-large-v3-turbo-ct2 "
    "mlx-community/whisper-large-v3-turbo-asr-fp16",
    809, "published-family-size", WHISPER,
)
record("Systran/faster-whisper-medium", 769, "published-family-size", WHISPER)
record("Systran/faster-whisper-small", 244, "published-family-size", WHISPER)
record(
    "Systran/faster-whisper-base csukuangfj/sherpa-onnx-whisper-base",
    74, "published-family-size", WHISPER,
)
record(
    "mlx-community/whisper-tiny-mlx Systran/faster-whisper-tiny "
    "csukuangfj/sherpa-onnx-whisper-tiny",
    39, "published-family-size", WHISPER,
)
record(
    "nvidia/parakeet-tdt-0.6b-v3 nvidia/parakeet-tdt-0.6b-v2 "
    "mlx-community/parakeet-tdt-0.6b-v3 "
    "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8 "
    "csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
    600, "model-family-label", "https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3",
)
record("UsefulSensors/moonshine-base", 61, "catalog-label", "backend/config/models.yaml")
record("UsefulSensors/moonshine-tiny", 27, "catalog-label", "backend/config/models.yaml")
record(
    "csukuangfj/sherpa-onnx-streaming-zipformer-en-20M-2023-02-17",
    20, "model-family-label", "backend/config/models.yaml",
)
record(
    "csukuangfj/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23",
    14, "model-family-label", "backend/config/models.yaml",
)
record("facebook/nllb-200-distilled-600M", 600, "model-family-label", "backend/config/models.yaml")
record(
    "OpenMOSS-Team/MOSS-TTS-Nano-100M OpenMOSS-Team/MOSS-TTS-Nano",
    100, "model-family-label", "backend/config/models.yaml",
)
record("KittenML/kitten-tts-mini-0.8", 80, "model-card", KITTEN)
record(
    "openbmb/VoxCPM2 mlx-community/VoxCPM2-8bit",
    2000, "published-family-size", VOXCPM,
)
record(
    "FunAudioLLM/Fun-CosyVoice3-0.5B-2512 "
    "Lourdle/Fun-CosyVoice3-0.5B-2512-GGUF",
    500, "model-family-label", "backend/config/models.yaml",
)
record("inclusionAI/Ming-3.0-tts-0.5b", 500, "model-family-label", "backend/config/models.yaml")
record("mlx-community/Kokoro-82M-bf16 csukuangfj/kokoro-int8-multi-lang-v1_1",
       82, "published-family-size", "https://huggingface.co/mlx-community/Kokoro-82M-bf16")
record("mlx-community/csm-1b-8bit", 1000, "model-family-label", "backend/config/models.yaml")
record("mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
       600, "model-family-label", "backend/config/models.yaml")
record("mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit",
       1700, "model-family-label", "backend/config/models.yaml")
record("mlx-community/Dia-1.6B", 1600, "model-family-label", "backend/config/models.yaml")
record("mlx-community/Llama-OuteTTS-1.0-1B-4bit", 1000, "model-family-label", "backend/config/models.yaml")
record("unsloth/Qwen3-1.7B-GGUF", 1700, "model-family-label", "mobile/contract/models.source.json")
record("kyutai/pocket-tts csukuangfj2/sherpa-onnx-pocket-tts-int8-2026-01-26",
       100, "published-family-size", POCKET)


def load(root: Path = ROOT) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    desktop = yaml.safe_load((root / "backend/config/models.yaml").read_text(encoding="utf-8"))
    licenses = json.loads((root / "backend/config/model_licenses.json").read_text(encoding="utf-8"))
    mobile = json.loads((root / "mobile/contract/models.source.json").read_text(encoding="utf-8"))
    if not isinstance(desktop, dict) or not isinstance(desktop.get("models"), list):
        raise ValueError("Invalid desktop model catalog")
    if not isinstance(licenses, dict) or not isinstance(licenses.get("models"), list):
        raise ValueError("Invalid license inventory")
    if not isinstance(mobile, dict) or not isinstance(mobile.get("models"), list):
        raise ValueError("Invalid mobile model manifest")
    return desktop, licenses, mobile


def dependency_ids(models: list[dict[str, Any]]) -> set[str]:
    found: set[str] = set()

    def collect(dependencies: list[dict[str, Any]]) -> None:
        for dependency in dependencies:
            found.add(dependency["repo_id"])
            collect(dependency.get("dependencies", []))
    for model in models:
        collect(model.get("dependencies", []))
    return found


def build(root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    desktop, licenses, mobile = load(root)
    catalog = {m.get("id") or m["repo_id"]: m for m in desktop["models"]}
    mobile_by_repo: dict[str, list[dict[str, Any]]] = {}
    for model in mobile["models"]:
        mobile_by_repo.setdefault(model["repo"], []).append(model)
    lic_records = licenses["models"]
    lic_ids = [item["id"] for item in lic_records]
    if len(lic_ids) != len(set(lic_ids)):
        raise ValueError("Duplicate model-license IDs")
    required = set(catalog) | dependency_ids(desktop["models"]) | set(mobile_by_repo)
    missing = required - set(lic_ids)
    if missing:
        raise ValueError("Model sources missing license records: " + ", ".join(sorted(missing)))
    unused = set(COUNTS) - set(lic_ids)
    if unused:
        raise ValueError("Stale parameter evidence IDs: " + ", ".join(sorted(unused)))
    rows: list[dict[str, Any]] = []
    for license_record in lic_records:
        model_id = license_record["id"]
        desktop_model = catalog.get(model_id)
        phone_models = mobile_by_repo.get(model_id, [])
        known = COUNTS.get(model_id)
        if known:
            value, evidence_type, source = known
        else:
            value, evidence_type, source = None, "unverified", None
        platform = desktop_model.get("platforms", []) if desktop_model else []
        rows.append({
            "model_id": model_id,
            "role": (desktop_model.get("role") if desktop_model else
                     ", ".join(sorted({p["capability"] for p in phone_models})) if phone_models else
                     "dependency / engine default"),
            "desktop_catalog": desktop_model is not None,
            "mobile_catalog": bool(phone_models),
            "parameter_millions_reported": value,
            "parameter_evidence": evidence_type,
            "parameter_source": source,
            "approx_download_gib": desktop_model.get("size_gb") if desktop_model else None,
            "platforms": platform or None,
            "license_review": license_record.get("review_status"),
            "commercial_use_reviewed": license_record.get("commercial_use", False),
        })
    summary = {
        "desktop_packages": len(catalog),
        "licensed_model_sources": len(lic_records),
        "mobile_packages": len(mobile["models"]),
        "known_parameter_reports": sum(r["parameter_millions_reported"] is not None for r in rows),
        "unverified_parameter_reports": sum(r["parameter_millions_reported"] is None for r in rows),
        "additional_dynamic_assets": len(licenses.get("dynamic_assets", [])),
        "note": "Counts are published architecture/family approximations, NOT exact tensor counts or total pipeline parameters. Null means not verified. No weights, inference or GPU are used.",
    }
    return rows, summary


def markdown(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# VoiceStudio offline model-parameter inventory",
        "",
        f"Desktop catalog: **{summary['desktop_packages']}** packages. "
        f"License sources: **{summary['licensed_model_sources']}** records. "
        f"Mobile catalog: **{summary['mobile_packages']}** packages.",
        f"Published/family parameter reports: **{summary['known_parameter_reports']}**; "
        f"not verified: **{summary['unverified_parameter_reports']}**.",
        "",
        "**Counts are approximate model-family sizes, not measured checkpoint tensor totals.** "
        "Quantized files keep parameter count but change disk usage; multi-model pipelines "
        "may have additional, uncounted components. Unknown is not zero.",
        "",
        "| Model/source | Purpose | Params (approx.) | Download (GiB) | Evidence |",
        "|---|---|---:|---:|---|",
    ]
    for row in rows:
        count = row["parameter_millions_reported"]
        size = row["approx_download_gib"]
        evidence = row["parameter_evidence"]
        if row["parameter_source"]:
            source = row["parameter_source"]
            evidence += f" ([source]({source}))" if source.startswith("https://") else f" (\`{source}\`)"
        lines.append(
            f"| \`{row['model_id']}\` | {row['role']} | "
            f"{(format(count / 1000, '.3g') + 'B') if count is not None and count >= 1000 else (str(count) + 'M') if count is not None else 'Unverified'} | "
            f"{size if size is not None else '—'} | {evidence} |"
        )
    lines += ["", "Source registries: \`backend/config/models.yaml\`, "
              "\`backend/config/model_licenses.json\`, \`mobile/contract/models.source.json\`.",
              f"Additional license-only dynamic assets: {summary['additional_dynamic_assets']} (not counted as individually enumerated model checkpoints).",
              "", "CPU-only check: no download, inference, tokenizer initialization, GPU probe or hosted API call.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    rows, summary = build(args.root)
    result = markdown(rows, summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "model-parameters.json").write_text(
            json.dumps({"summary": summary, "models": rows}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (args.output_dir / "model-parameters.md").write_text(result, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
