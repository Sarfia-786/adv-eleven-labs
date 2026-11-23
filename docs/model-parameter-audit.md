# Model parameter inventory

The desktop catalog, mobile manifest and model-source registry overlap. The audit reconciles their identifiers, including separately selectable packages from the same repository and the dependencies of model pipelines. The license validator also checks model identifiers embedded in Python code.

On the audited revision, the registry contains **73 named sources**. There are **46 desktop packages**, **11 mobile packages**, and **7 additional runtime-selected asset families**. A model used by both the desktop and phone counts once in the source inventory.

## Read the counts

The Markdown table lists every source with its purpose, parameter count, scope, evidence and catalog download size where available. M means million and B means billion. A model family and its quantized conversions can share a parameter count while using different amounts of memory and disk.

For example, IndexTTS‑2.5 publishes 800M for its GPT backbone. Its speech decoder and vocoder add weights. Supertonic 3 publishes about 99M across the public ONNX components. Some entries package several interchangeable checkpoints. The report identifies these entries and explains which selection determines their total. It gives known component sizes separately for runtime-selected families such as AudioSeal and HTDemucs.

The JSON includes the original registry ID, platforms, scope, evidence URL or catalog path, and a nullable `parameter_millions_reported`. The `summary.dynamic_assets` list identifies the runtime-selected asset families. Model licensing and commercial-use review continue to come from `backend/config/model_licenses.json`.

## Generate the report

From the repository root, run the following commands with Python 3.11 or newer.

```sh
python -m pip install 'pyyaml==6.0.3'
python tests/test_model_parameter_inventory.py -v
python scripts/model_parameter_inventory.py --output-dir /tmp/model-parameter-report
python scripts/check_model_licenses.py
```

The script writes `model-parameters.md` and `model-parameters.json`. The [CPU inventory workflow](../.github/workflows/model-parameters.yml) publishes the table in its GitHub Actions summary and uploads both files as the `voice-model-parameters` artifact for 14 days. It runs for catalog and code changes on pull requests and on pushes to `main` and the audit branch. It also supports manual dispatch.

The Ubuntu runner can validate this entire inventory with PyYAML and the Python standard library. The tests use offline fixtures and the checked-out repository. The job records the allocated CPU and memory. Actual speech generation, GPU memory requirements, and Apple MLX or CUDA inference require separate hardware-specific tests.
