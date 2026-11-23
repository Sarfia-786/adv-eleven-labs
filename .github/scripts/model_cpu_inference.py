"""Explicit networked download followed by a fresh, offline CPU inference process per model."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from services import sherpa_dictation

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "backend/assets/samples"
REGISTRY = json.loads((ROOT / "backend/config/model_licenses.json").read_text())["models"]
KITTEN = "KittenML/kitten-tts-mini-0.8"


def groups() -> dict[str, list[str]]:
    faster = [row["id"] for row in REGISTRY if "faster-whisper" in row["engines"]]
    return {
        "sherpa": [spec.repo_id for spec in sherpa_dictation.list_specs()],
        "whisper-small": [repo for repo in faster if "large" not in repo],
        "whisper-large": [repo for repo in faster if "large" in repo],
        "kitten": [KITTEN],
    }


def download(repo: str, cache: Path) -> Path:
    from huggingface_hub import snapshot_download

    record = next(row for row in REGISTRY if row["id"] == repo)
    revision = record.get("runtime_revision") or record["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"Missing immutable revision for {repo}")
    spec = sherpa_dictation.get_spec(repo)
    if spec:
        files = list(spec.files.values())
    elif repo == KITTEN:
        files = ["config.json", "*.onnx", "*.npz"]
    else:
        files = ["config.json", "model.bin", "preprocessor_config.json", "tokenizer.json", "vocabulary.*"]
    print(f"Downloading {repo}@{revision}", flush=True)
    snapshot = Path(snapshot_download(repo, revision=revision, cache_dir=cache, allow_patterns=files))
    if snapshot.name != revision:
        raise RuntimeError(f"Unexpected revision in {snapshot}")
    # Kitten's SDK looks up refs/main even when offline. This private cache
    # contains only the immutable revision fetched for this model.
    if repo == KITTEN:
        ref = snapshot.parents[1] / "refs/main"
        ref.parent.mkdir(exist_ok=True)
        ref.write_text(revision)
    return snapshot


def verify_transcript(transcript: str, chinese: bool) -> None:
    print(f"Transcript: {transcript!r}", flush=True)
    if chinese:
        from core.personalities import get_personality

        expected = get_personality("mandarin_sichuan")["script"]
        characters = re.compile(r"[\u4e00-\u9fff]")
        score = SequenceMatcher(None, characters.findall(expected), characters.findall(transcript)).ratio()
        if score < 0.4:
            raise ValueError(f"Mandarin transcript similarity {score:.2f} is below 0.4")
    else:
        anchors = {"meeting", "tuesday", "quarterly", "report"}
        if len(anchors.intersection(re.findall(r"[a-z]+", transcript.lower()))) < 2:
            raise ValueError("Transcript contains fewer than two of the fixture's four keywords")


def infer(repo: str, snapshot: Path) -> None:
    if repo == KITTEN:
        import numpy as np
        from services.tts_backend import KittenTTSBackend

        engine = KittenTTSBackend()
        signal = engine.generate("Today is a beautiful day for a walk.").detach().cpu().numpy().ravel()
        seconds = signal.size / engine.sample_rate
        if not (0.5 <= seconds <= 20 and np.isfinite(signal).all() and np.abs(signal).max() > 0.001):
            raise ValueError(f"Invalid synthesized waveform ({seconds:.2f} seconds)")
        print(f"Generated {seconds:.2f} seconds at {engine.sample_rate} Hz", flush=True)
        return

    spec = sherpa_dictation.get_spec(repo)
    chinese = spec is not None and spec.id == "sherpa-zipformer-zh-14m"
    fixture = (SAMPLES / "voice_design/demo_voice_design_mandarin_sichuan.wav" if chinese
               else SAMPLES / "dictation/en_conversational.wav")
    if spec:
        from services.asr_backend import SherpaDictationBackend

        transcript = SherpaDictationBackend(spec.id).transcribe(str(fixture))["text"]
    else:
        from faster_whisper import WhisperModel

        engine = WhisperModel(str(snapshot), device="cpu", compute_type="int8", cpu_threads=4,
                              local_files_only=True)
        segments, _ = engine.transcribe(str(fixture), language="en", beam_size=1, vad_filter=False)
        transcript = " ".join(segment.text for segment in segments)
    verify_transcript(transcript, chinese)


def main() -> None:
    from httpx import HTTPError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("group", choices=groups())
    parser.add_argument("--infer", nargs=2, metavar=("REPO", "SNAPSHOT"))
    args = parser.parse_args()
    if args.infer:
        repo, snapshot = args.infer
        infer(repo, Path(snapshot))
        return

    results = {}
    for repo in groups()[args.group]:
        try:
            with tempfile.TemporaryDirectory() as work:
                cache = Path(work) / "hub"
                snapshot = download(repo, cache)
                env = dict(os.environ, HF_HOME=work, HF_HUB_CACHE=str(cache), HF_HUB_OFFLINE="1",
                           TRANSFORMERS_OFFLINE="1", OMNIVOICE_DATA_DIR=str(Path(work) / "data"))
                subprocess.run([sys.executable, __file__, args.group, "--infer", repo, str(snapshot)],
                               env=env, check=True, timeout=600)
            results[repo] = "Passed"
        # An SDK, download or native-process failure must not suppress the results
        # for later checkpoints that share this runner.
        except (OSError, ValueError, RuntimeError, HTTPError, subprocess.SubprocessError) as error:
            print(f"FAIL {repo}: {error}", file=sys.stderr, flush=True)
            results[repo] = "Failed"
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as output:
            print("| Checkpoint | CPU inference |", "| --- | --- |", sep="\n", file=output)
            for repo, status in results.items():
                print(f"| {repo} | {status} |", file=output)
    failed = [repo for repo, status in results.items() if status == "Failed"]
    if failed:
        raise SystemExit("Failed models: " + ", ".join(failed))


if __name__ == "__main__":
    main()
