# Model-parameter audit on GitHub Actions (CPU only)

This fork has **three overlapping inventories**, not three disjoint model sets:

- **46** desktop/backend model packages in `backend/config/models.yaml`;
- **73** model-source and dependency records in `backend/config/model_licenses.json`;
- **11** mobile model packages in `mobile/contract/models.source.json`.
- The license registry also describes **7** non-enumerated dynamic asset families. They
  are not independent verified pretrained checkpoints with known parameters.

`scripts/model_parameter_inventory.py` visits **every license record** and
cross-checks the desktop and mobile catalogs plus nested pipeline dependencies.
It reports one line for each model-source ID with reported parameter count,
provenance, backend/phone inclusion, optional desktop download size, and the
existing licensing review state. If no reliable count is recorded, the value
is JSON null and the Markdown report reads **Unverified**. This is intentional.
Counts are rounded published *architecture/family* counts: a conversion or
quantization does not shrink number of parameters; an archive combining several
networks does not have one safe count. Disk size, resident memory, installed
state and parameter counts are separate measurements.

## Run locally

```sh
python -m pip install 'pyyaml==6.0.3'
python -m unittest discover -s tests -p test_model_parameter_inventory.py -v
python scripts/check_model_licenses.py
python scripts/model_parameter_inventory.py --output-dir /tmp/model-parameter-report
```

The resulting `model-parameters.md` contains the complete itemized table;
`model-parameters.json` is machine-readable and preserves unverified values.
The script never loads checkpoints or imports torch.

## GitHub-hosted execution

The `Model parameters (CPU-only inventory)` workflow runs on
`ubuntu-24.04` for the audit branch, matching pull requests and manual
dispatches. The standard **public-repository** runner is advertised as
**4 vCPU, 16 GiB RAM, 14 GiB SSD**, and the job logs actual allocated CPU and
memory information. It installs only PyYAML, runs its focused tests and the
existing source-code licence scan, and uploads Markdown and JSON as a
`voice-model-parameters` artifact (14-day retention). It also puts a
complete table in the GitHub Actions step summary.

This is a **CPU metadata audit**, not a claim that 73 engines have run inference.
Four CPUs cannot execute CUDA-only or Apple MLX paths, and the runner's disk
is not enough for every optional multi-GB model plus dependencies and audio
fixtures. It would be misleading to attempt bulk weight downloads or skip
GPU tests but call them successful. Actual inference and checkpoint-level
exact tensor counts need opted-in model downloads, revision-specific checks,
licence/usage rights, device-appropriate hardware, and separate reports.

A repository PR may remain draft while the CLA is unsigned; the CLA-gated
general CI jobs are not a substitute for a real successful full test matrix.
Neither the workflow nor this report signs a CLA or relaxes branch protection.

## Source attribution and follow-ups

Architectural numbers reference OpenAI's Whisper family table, the VoiceStudio
catalog's explicit parameter labels, or published model cards such as VoxCPM2,
KittenTTS and Pocket TTS. These are *reported approximations*, not a full
weight-by-weight count, and should not be used to infer commercial clearance.
The licensing review continues to be authoritative for permitted use.
For unverified IDs, review the exact model revision and all constituent files
before adding a numerical entry; do not derive it from GiB or a marketing version.
