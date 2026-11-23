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
from pathlib import Path
from typing import Any

import yaml

from check_model_licenses import catalog_ids

ROOT = Path(__file__).resolve().parents[1]
WHISPER = "https://github.com/openai/whisper#available-models-and-languages"
VOXCPM = "https://huggingface.co/openbmb/VoxCPM2"
KITTEN = "https://huggingface.co/KittenML/kitten-tts-mini-0.8"
POCKET = "https://huggingface.co/kyutai/pocket-tts"

# Rounded, *reported architecture* millions, never fabricated tensor totals.
# For quantized and converted copies, this is the original architecture's
# approximate size; quantization does not reduce the number of parameters.
# Entries with multiple separate networks deliberately remain unknown.
COUNTS: dict[str, tuple[float, str, str]] = {}


def record(names: str, millions: float, provenance: str, source: str) -> None:
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


record(
    "k2-fsa/OmniVoice "
    "Serveurperso/OmniVoice-GGUF",
    600, "speech backbone",
    "https://huggingface.co/Serveurperso/OmniVoice-GGUF",
)
record(
    "audio-cpp/audio.cpp-gguf:dots-tts-soar-q8_0 "
    "rednote-hilab/dots.tts-soar",
    2000, "published model family",
    "https://huggingface.co/rednote-hilab/dots.tts-soar",
)
record(
    "Systran/faster-distil-whisper-large-v3",
    756, "published model family",
    "https://huggingface.co/distil-whisper/distil-large-v3",
)
record(
    "csukuangfj/sherpa-onnx-streaming-paraformer-bilingual-zh-en",
    220, "published streaming model family",
    "https://github.com/modelscope/FunASR#model-zoo",
)
record(
    "pyannote/segmentation-3.0",
    1.47, "architecture reported by the MLX conversion",
    "https://huggingface.co/mlx-community/pyannote-segmentation-3.0-mlx",
)
record(
    "pyannote/wespeaker-voxceleb-resnet34-LM",
    6.6, "architecture reported by the MLX conversion",
    "https://huggingface.co/mlx-community/wespeaker-voxceleb-resnet34-LM",
)
record(
    "mlx-community/Chatterbox-TTS-4bit",
    500, "published speech model family",
    "https://huggingface.co/ResembleAI/chatterbox",
)
record(
    "mlx-community/MeloTTS-English-v3-MLX",
    51.8, "Hub model size for the MLX checkpoint",
    "https://huggingface.co/mlx-community/MeloTTS-English-v3-MLX",
)
record(
    "IndexTeam/IndexTTS-2.5",
    800, "GPT backbone only",
    "https://huggingface.co/IndexTeam/IndexTTS-2.5",
)
record(
    "Supertone/supertonic-3 "
    "csukuangfj2/sherpa-onnx-supertonic-3-tts-int8-2026-05-11",
    99, "published total across the public ONNX models",
    "https://huggingface.co/Supertone/supertonic-3",
)
record(
    "OpenMOSS-Team/MOSS-TTS-v1.5",
    8000, "published model family",
    "https://huggingface.co/OpenMOSS-Team/MOSS-TTS-v1.5",
)
record(
    "OpenMOSS-Team/MOSS-Audio-Tokenizer",
    1600, "encoder and decoder combined",
    "https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer",
)
record(
    "OpenMOSS-Team/MOSS-SoundEffect-v2.0",
    1300, "diffusion transformer only",
    "https://huggingface.co/OpenMOSS-Team/MOSS-SoundEffect-v2.0",
)
record(
    "facebook/w2v-bert-2.0",
    600, "speech encoder",
    "https://huggingface.co/facebook/w2v-bert-2.0",
)
record(
    "funasr/campplus",
    7.2, "published speaker encoder",
    "https://github.com/modelscope/FunASR#model-zoo",
)
record(
    "nvidia/bigvgan_v2_22khz_80band_256x",
    112, "vocoder generator",
    "https://github.com/NVIDIA/BigVGAN#pretrained-models",
)
record(
    "iic/SenseVoiceSmall",
    234, "published ASR model",
    "https://github.com/modelscope/FunASR#model-zoo",
)
record(
    "eustlb/higgs-audio-v2-tokenizer",
    200, "Hub model size for the audio tokenizer",
    "https://huggingface.co/eustlb/higgs-audio-v2-tokenizer",
)
record(
    "csukuangfj/kitten-mini-en-v0_1-fp16",
    80, "published v0.1 model family",
    "https://huggingface.co/KittenML/kitten-tts-mini-0.1",
)
record(
    "csukuangfj/vits-piper-en_US-lessac-medium",
    15.7, "published benchmark for original Lessac Medium",
    "https://github.com/ayutaz/piper-plus/blob/dev/README_EN.md#benchmark",
)
record(
    "k2-fsa/ZipVoice",
    123, "ZipVoice-Distill speech model, excluding the separate vocoder",
    "https://arxiv.org/html/2506.13053v1",
)

# Interpret partial counts and explain which selections prevent a single total.
PARAMETER_NOTES = {
    "audio-cpp/audio.cpp-gguf": (
        "The selected bundle contains two independent models, Breeze-TTS-2 and Sortformer 4spk v1. A combined count is unverified."
    ),
    "csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20": (
        "The bilingual checkpoint uses a different vocabulary and architecture from the 14M and 20M Zipformers. Its count is unverified."
    ),
    "pyannote/speaker-diarization-3.1": (
        "Configuration that loads segmentation-3.0 and WeSpeaker ResNet34-LM. Both components are itemized separately."
    ),
    "lj1995/GPT-SoVITS": (
        "This source distributes several GPT and SoVITS checkpoints. The model version and pair determine the total."
    ),
    "netease-youdao/Confucius4-TTS": (
        "The release has separate text-to-semantic and semantic-to-acoustic weights. A combined count is unverified."
    ),
    "ggerganov/whisper.cpp": (
        "The user selects the GGML file. The registered Whisper family ranges from 39M (tiny) to 1.55B (large)."
    ),
    "k2-fsa/OmniVoice": (
        "The 600M figure describes the Qwen speech backbone. The separate audio tokenizer is outside that figure."
    ),
    "Serveurperso/OmniVoice-GGUF": (
        "The mobile package also includes the audio tokenizer. Its weights are outside the backbone count."
    ),
    "mlx-community/Chatterbox-TTS-4bit": (
        "Resemble reports 500M for the speech model. The MLX package also contains other tensors."
    ),
    "IndexTeam/IndexTTS-2.5": (
        "The speech-to-mel decoder and vocoder are additional components."
    ),
    "OpenMOSS-Team/MOSS-SoundEffect-v2.0": (
        "The text encoder and audio decoder are additional components."
    ),
}

# Published examples for families whose installed version is selected by the SDK.
DYNAMIC_COUNTS = {
    "audioseal_wm_16bits / audioseal_detector_16bits": (
        ("AudioSeal generator (published benchmark)", 14.68, "https://proceedings.mlr.press/v267/liu25ap.html"),
        ("AudioSeal detector (published benchmark)", 8.65, "https://proceedings.mlr.press/v267/liu25ap.html"),
    ),
    "htdemucs": (
        ("Four-stem HTDemucs architecture", 42, "https://huggingface.co/jasonvassallo/demucs-htdemucs-mlx"),
    ),
    "fsmn-vad / cam++": (
        ("FSMN-VAD", 0.4, "https://github.com/modelscope/FunASR#model-zoo"),
        ("CAM++", 7.2, "https://github.com/modelscope/FunASR#model-zoo"),
    ),
}


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


def build(root: Path = ROOT) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    desktop, licenses, mobile = load(root)
    catalog = {m.get("id") or m["repo_id"]: m for m in desktop["models"]}
    if len(catalog) != len(desktop["models"]):
        raise ValueError("Duplicate desktop package IDs")
    mobile_by_repo: dict[str, list[dict[str, Any]]] = {}
    for model in mobile["models"]:
        mobile_by_repo.setdefault(model["repo"], []).append(model)
    lic_records = licenses["models"]
    lic_ids = [item["id"] for item in lic_records]
    if len(lic_ids) != len(set(lic_ids)):
        raise ValueError("Duplicate model-license IDs")
    required = set(catalog_ids(desktop["models"])) | set(mobile_by_repo)
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
        engine_names = ", ".join(license_record.get("engines", []))
        if desktop_model:
            role = desktop_model["role"]
        elif phone_models:
            role = ", ".join(sorted({m["capability"] for m in phone_models}))
        elif engine_names:
            role = f"Engine component ({engine_names})"
        else:
            role = "Pipeline component"
        platform = desktop_model.get("platforms", []) if desktop_model else []
        rows.append({
            "model_id": model_id,
            "role": role,
            "desktop_catalog": desktop_model is not None,
            "mobile_catalog": bool(phone_models),
            "parameter_millions_reported": value,
            "parameter_evidence": evidence_type,
            "parameter_source": source,
            "source_url": license_record.get("source_url"),
            "parameter_note": PARAMETER_NOTES.get(model_id),
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
        "dynamic_assets": [
            {
                "id": d["id"],
                "source_url": d.get("source_url"),
                "published_components": [
                    {"name": name, "millions": value, "source": url}
                    for name, value, url in DYNAMIC_COUNTS.get(d["id"], ())
                ],
            }
            for d in licenses.get("dynamic_assets", [])
        ],
        "note": "Counts describe published models or the named components. Null marks an unverified single total.",
    }
    return rows, summary


def markdown(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# VoiceStudio model-parameter inventory",
        "",
        f"{summary['licensed_model_sources']} registered sources cover "
        f"{summary['desktop_packages']} desktop and {summary['mobile_packages']} mobile "
        "packages, including shared models and dependencies.",
        f"{summary['known_parameter_reports']} sources have a reported parameter count. "
        f"{summary['unverified_parameter_reports']} have no verified single total.",
        "",
        "M = million parameters. B = billion. The scope column identifies backbone, "
        "component and family counts. Quantized variants can share the same architecture.",
        "",
        "| Model or source | Purpose | Parameters | Download (GiB) | Scope and evidence |",
        "|---|---|---:|---:|---|",
    ]
    for row in rows:
        count = row["parameter_millions_reported"]
        display_count = "Unverified"
        if count is not None:
            display_count = f"{count / 1000:.3g}B" if count >= 1000 else f"{count:g}M"
        size = row["approx_download_gib"]
        evidence = row["parameter_evidence"]
        source = row["parameter_source"] or row["source_url"]
        if source:
            label = "source" if row["parameter_source"] else "model listing"
            evidence += f" ([{label}]({source}))" if source.startswith("https://") else f" (`{source}`)"
        if row["parameter_note"]:
            evidence += f". {row['parameter_note']}"
        lines.append(
            f"| `{row['model_id']}` | {row['role']} | {display_count} | "
            f"{size if size is not None else '—'} | {evidence} |"
        )
    lines.extend(["", "## Runtime-selected assets", "",
                  "These families depend on the SDK, language or user selection.", ""])
    for asset in summary["dynamic_assets"]:
        source = asset["source_url"]
        name = asset["id"]
        label = f"[{name}]({source})" if source else name
        parts = [
            f"{c['name']} [{c['millions']:g}M]({c['source']})"
            for c in asset["published_components"]
        ]
        lines.append(f"- {label} — " + (", ".join(parts) if parts else "selection-dependent"))
    return "\n".join(lines) + "\n"


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
