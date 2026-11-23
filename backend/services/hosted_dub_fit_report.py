"""Describe one language track using the Smart Fit plan and its measured render."""

import math
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal

from services.fit_planner import MAX_AUDIO_RATE_HARD, FitPlan


def _ms(seconds: float) -> int:
    if (
        isinstance(seconds, bool)
        or not isinstance(seconds, (int, float))
        or not math.isfinite(seconds)
        or seconds < 0
    ):
        raise ValueError("expected finite, nonnegative seconds")
    return int((Decimal(str(seconds)) * 1000).to_integral_value(rounding=ROUND_HALF_UP))


def build_fit_report(
    plan: FitPlan,
    natural_durations_s: Sequence[float],
    fitted_segments: Sequence[Mapping],
    *,
    track_duration_s: float | None,
) -> dict:
    """Join natural WAV lengths in plan order to measured final cues by segment ID.

    The renderer supplies its fitted_segments ({id, start, end} in seconds) and
    the decoded master duration. Either can be absent for an unfinished render.
    Signed deviations compare the measured length to the requested source length.
    """
    source_ms = (
        _ms(plan.orig_duration) if plan.orig_duration or not plan.segments else None
    )
    track_ms = None if track_duration_s is None else _ms(track_duration_s)
    ids = {s.seg_id for s in plan.segments}
    if len(ids) != len(plan.segments):
        raise ValueError("the fit plan contains duplicate segment IDs")
    if len(plan.segments) != len(natural_durations_s):
        raise ValueError("provide one natural speech duration per planned segment")

    measured = {}
    for cue in fitted_segments:
        seg_id = cue.get("id")
        if not isinstance(seg_id, str) or seg_id not in ids or seg_id in measured:
            raise ValueError("rendered cues must have unique IDs from the fit plan")
        start, end = cue.get("start"), cue.get("end")
        start_ms, end_ms = _ms(start), _ms(end)
        if end < start:
            raise ValueError(f"reversed rendered cue for {seg_id}")
        measured[seg_id] = start_ms, end_ms

    rows = []
    for segment, natural_s in zip(plan.segments, natural_durations_s, strict=True):
        original_start, original_end = _ms(segment.orig_start), _ms(segment.orig_end)
        original_duration = original_end - original_start
        warnings = []
        if segment.status == "overflow_trimmed":
            warnings.append("stretch_limit_exceeded")
        start_ms = end_ms = duration_ms = deviation_ms = None
        if segment.seg_id in measured:
            start_ms, end_ms = measured[segment.seg_id]
            if track_ms is not None and end_ms > track_ms:
                start_ms, end_ms = min(start_ms, track_ms), track_ms
                warnings.append("clipped_at_track_end")
            duration_ms = end_ms - start_ms
            deviation_ms = duration_ms - original_duration
            if deviation_ms < 0:
                warnings.append("shorter_than_requested")
            elif deviation_ms > 0:
                warnings.append("longer_than_requested")
        else:
            warnings.append("missing_render")
        rows.append(
            {
                "id": segment.seg_id,
                "requested_start_ms": original_start,
                "requested_end_ms": original_end,
                "original_duration_ms": original_duration,
                "natural_duration_ms": _ms(natural_s),
                "planned_start_ms": _ms(segment.new_start),
                "planned_end_ms": _ms(segment.new_end),
                "planned_overflow_ms": _ms(segment.overflow_s),
                "audio_rate": segment.audio_rate,
                "video_ratio": segment.video_ratio,
                "planner_status": segment.status,
                "fitted_start_ms": start_ms,
                "fitted_end_ms": end_ms,
                "fitted_duration_ms": duration_ms,
                "deviation_ms": deviation_ms,
                "warnings": warnings,
            }
        )

    params = plan.params
    return {
        "original_duration_ms": source_ms,
        "planned_duration_ms": _ms(plan.total_duration),
        "fitted_duration_ms": track_ms,
        "deviation_ms": track_ms - source_ms
        if track_ms is not None and source_ms is not None
        else None,
        "stretch_limits": {
            "min_audio_rate": params.min_audio_rate,
            "max_audio_only_rate": params.max_audio_only_rate,
            "audio_rate_cap": params.audio_rate_cap
            if params.allow_video_retime
            else MAX_AUDIO_RATE_HARD,
            "video_slow_cap": params.video_slow_cap
            if params.allow_video_retime
            else 1.0,
        },
        "segments": rows,
    }
