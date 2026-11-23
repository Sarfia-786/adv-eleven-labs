# Hosted commercial model licence review (#8)

**Status: blocked for every real production model as of 2026-11-23.** This
document does not grant permission or imply that a model can be used in a
commercial hosted service. The original upstream author, credit and source
URLs remain in `backend/config/model_licenses.json` and
[`docs/licensing/model-inventory.md`](licensing/model-inventory.md).

## Gate and contract

The policy lives in `backend/services/hosted_model_policy.py`, separate from
the Studio's local acknowledgement flow (`model_acceptance.py`). Call
`require_paid_inference(model_id, revision, components)` from the worker
**immediately before** loading or running paid inference. It raises
`HostedModelDenied` with `code=hosted_model_not_permitted` and deterministic
`blockers` on denial. There is no local acceptance, environment switch,
network fallback, or implicit approval path. Do **not** retry denied jobs using
another model unless that selection independently passes the same gate.

Each `components` entry is exactly
`{"id":"org/repo","revision":"<40 lowercase hex SHA>","root":"/absolute/local/snapshot"}`.
Pass **all** models, tokenizers, vocoders and other model-bearing dependencies
actually loaded by the job, with their resolved runtime revisions. The gate
checks the complete recursive dependency graph from the licence registry **and**
the configured catalogue, rejects extras/missing or duplicate components, and
checks each pinned artifact's length and SHA-256 on disk. The snapshot must
remain immutable from check through execution: deployments should mount it
read-only; a concurrent mutator would otherwise create a time-of-check/time-
of-use race. A hash of files that workers do **not** actually load is not proof
of a compliant inference.

A complete production record must establish: matching `revision` and
`runtime_revision`, `review_status=cleared`, `commercial_use=true`,
`commercial_inference=permitted`, `commercial_outputs=permitted`,
`review_scope=hosted_paid_inference_and_outputs`, a named `reviewed_by` and
ISO `reviewed_at`, `component_closure=complete`, an explicit
`required_components` list, `upstream_access=not_required`, complete
artifact hashes, hashed source documents covering every artifact, permissible
document redistribution, original credit/source, and no unresolved variants.
A permissive licence label alone is not sufficient. Other review scopes and
gated provider assent are not supported by this automated policy.

## Offline deployment check

Create a deployment manifest of the exact selections that workers will load:

```json
{
  "schema_version": 1,
  "models": [
    {
      "model_id": "org/model",
      "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "components": [
        {
          "id": "org/model",
          "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "root": "/opt/voice/immutable/model-snapshot"
        }
      ]
    }
  ]
}
```

The values above are *illustrative*, **not an approved real model**. Add every
dependency to `components`; do not copy this placeholder directly into
deployment. Run offline from the repository root:

```sh
python scripts/check_hosted_model_licenses.py --manifest /path/to/deployment-models.json
python -m pytest -q tests/test_hosted_model_policy.py tests/test_model_licenses.py
python scripts/check_model_licenses.py
```

Preflight prints JSON and exits 0 only if all models pass; it exits 1 on
denial/unreadable manifest. This is a deployment diagnostic, not a cached grant.
Every worker still calls `require_paid_inference` on its exact loaded snapshot.
No hosted job integration is part of issue #8; worker integration belongs to
[#10](https://github.com/Sarfia-786/adv-eleven-labs/issues/10).

## Remaining real-model decisions

1. **All production models:** determine the governing terms of the precise
   runtime revision, including converted/quantized weights and each dependency;
   resolve `component_closure`, final artifact bytes, SHA-256, download
   provenance, and complete licence/NOTICE source documents. No current
   production row has all of this.
2. **Commercial inference:** obtain documented rights specifically covering
   hosted paid use, not just a model-card licence label or a local click-through.
   OmniVoice, OmniVoice-GGUF, NLLB and Llama-OuteTTS have restrictive signals
   already recorded; a separate commercial grant would require its own review.
3. **Outputs:** review separately whether generated audio may be commercially
   delivered, sublicensed or redistributed and whether training/derivative
   restrictions apply. Unknown output terms block approval.
4. **Mixed bundles and variants:** establish each selected artifact's upstream
   origin and terms (notably audio.cpp GGUF variants), before marking a complete
   dependency graph.
5. **Access and redistribution:** provider-gated checkpoints need verified
   provider-specific agreements; the current automated policy deliberately
   refuses `upstream_access` other than `not_required`. Preserve attribution
   and NOTICE obligations in deployment/export procedures.
6. **Dynamic weights and SDK downloads:** model-folder overrides, unpinned
   `main` references, SDK-selected ASR/VAD/alignment assets, and phone/external
   assets cannot inherit approval from a related model.
7. **Operational controls:** workers must supply actual resolved snapshots and
   enforce read-only files for the duration of the job; voice consent, input
   rights and privacy are separate checks, not replaced by this licence gate.

Synthetic passing fixtures in `tests/test_hosted_model_policy.py` are
fictional and never appear in the production registry. They demonstrate the
interface, not any real-model clearance. This PR deliberately does not change
tenant persistence, hosted routes, or the contributor's #4 branch.
