# Dubbing fit reports

Use `build_fit_report` once per target language. Give it the same natural
WAV durations used by Smart Fit, the rendered segment cues keyed by ID, and
the decoded master length (frames divided by sample rate). The returned
dictionary can be serialized as JSON.

```python
from services.fit_planner import plan_fit
from services.hosted_dub_fit_report import build_fit_report

requested = [{"id": "intro", "start": 0.5, "end": 1.5}]
natural = [0.6]
plan = plan_fit(requested, natural, total_dur_s=2.0)
report = build_fit_report(
    plan, natural,
    fitted_segments=[{"id": "intro", "start": 0.5, "end": 1.2}],
    track_duration_s=2.0,
)
# 700 ms of fitted speech in a requested 1000 ms interval, on a 2000 ms master.
assert report["segments"][0]["deviation_ms"] == -300
```

All published times are integer milliseconds. Each boundary rounds to the
nearest millisecond, with ties rounded up. Durations are differences between
the published boundaries. For each segment, `deviation_ms` is measured speech
duration minus the requested interval length. For the whole track it is the
decoded master duration minus the source duration, including gaps, overlap
and silence. A zero source duration with nonempty segments means the planner
did not know the source duration.

`planned_start_ms` and `planned_end_ms` bound the slot on the retimed track.
The planned slot can include borrowed silence. `audio_rate` and `video_ratio`
are the planner's chosen factors. `stretch_limits` records the slowdown floor,
audio-only threshold, and audio and video caps for the mode used.

| Segment warning | Meaning |
| --- | --- |
| `stretch_limit_exceeded` | Speech exceeds the planner's limits. `planned_overflow_ms` gives the residual. |
| `missing_render` | No final cue was available for this ID. Its measured fields are null. |
| `clipped_at_track_end` | The measured cue extended beyond the decoded master. Only the audible interval is counted. |
| `shorter_than_requested` or `longer_than_requested` | Measured speech differs from the requested interval by at least one reported millisecond. |

Pass an empty cue list and `track_duration_s=None` when a render fails before
producing audio. The report retains the planner diagnostics. Hosted endpoint
integration is tracked in #18.
