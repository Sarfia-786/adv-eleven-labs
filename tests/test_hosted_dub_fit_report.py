import pytest
from services.fit_planner import FitParams, plan_fit
from services.hosted_dub_fit_report import build_fit_report


def cue(segment_id, start, end):
    return {"id": segment_id, "start": start, "end": end}


def report(requested, natural, source_duration, fitted, track_duration, params=None):
    plan = plan_fit(requested, natural, source_duration, params)
    return build_fit_report(plan, natural, fitted, track_duration_s=track_duration)


def test_measured_exact_fit_uses_milliseconds_at_shared_boundaries():
    requested = [cue("a", 0.0005, 0.5015)]
    result = report(requested, [0.501], 0.5015, requested, 0.5015)
    line = result["segments"][0]
    assert (line["fitted_start_ms"], line["fitted_end_ms"]) == (1, 502)
    assert line["original_duration_ms"] == line["fitted_duration_ms"] == 501
    assert line["deviation_ms"] == 0 and line["warnings"] == []
    assert result["fitted_duration_ms"] == 502 and result["deviation_ms"] == 0


def test_measured_shorter_and_longer_lines_can_share_a_track_with_gaps():
    requested = [cue("a", 0.5, 1.5), cue("b", 2, 3)]
    fitted = [cue("b", 2, 3.1), cue("a", 0.5, 1.2)]
    result = report(requested, [0.6, 1.1], 4, fitted, 4.05)
    short, long = result["segments"]
    assert (short["id"], short["natural_duration_ms"], short["fitted_duration_ms"]) == (
        "a",
        600,
        700,
    )
    assert (short["deviation_ms"], short["warnings"]) == (
        -300,
        ["shorter_than_requested"],
    )
    assert (long["id"], long["deviation_ms"], long["warnings"]) == (
        "b",
        100,
        ["longer_than_requested"],
    )
    assert short["planned_end_ms"] == 1950  # absorbed silence, with the 50 ms guard
    assert result["original_duration_ms"] == result["planned_duration_ms"] == 4000
    assert (
        result["fitted_duration_ms"] == 4050
    )  # decoded master includes the silent gaps
    assert result["deviation_ms"] == 50


def test_infeasible_line_reports_the_cap_without_inventing_delivered_speech():
    result = report(
        [cue("too-long", 0, 1)],
        [4],
        1,
        [],
        None,
        FitParams(allow_video_retime=False, audio_rate_cap=1.1),
    )
    line = result["segments"][0]
    assert line["audio_rate"] == result["stretch_limits"]["audio_rate_cap"] == 1.8
    assert result["stretch_limits"]["video_slow_cap"] == 1
    assert line["planned_overflow_ms"] == 1222
    assert line["warnings"] == ["stretch_limit_exceeded", "missing_render"]
    assert line["fitted_duration_ms"] is line["deviation_ms"] is None
    assert result["fitted_duration_ms"] is result["deviation_ms"] is None


def test_overlap_uses_shared_retimed_positions_and_counts_master_once():
    result = report(
        [cue("a", 0, 2), cue("b", 1, 3)],
        [4, 2],
        3,
        [cue("a", 0, 3), cue("b", 1.5, 3.5)],
        4,
        FitParams(max_audio_only_rate=1, audio_rate_cap=1, video_slow_cap=1.5),
    )
    first, second = result["segments"]
    assert result["stretch_limits"]["audio_rate_cap"] == 1
    assert first["video_ratio"] == 1.5
    assert first["planned_overflow_ms"] == 1000
    assert first["warnings"] == ["stretch_limit_exceeded", "longer_than_requested"]
    assert second["planned_start_ms"] == second["fitted_start_ms"] == 1500
    assert second["fitted_duration_ms"] == 2000 and second["warnings"] == []
    assert result["planned_duration_ms"] == result["fitted_duration_ms"] == 4000


def test_rendered_cue_is_clipped_to_the_decoded_track_end():
    result = report([cue("s", 0, 1)], [1], 1, [cue("s", 0, 1.01)], 0.998)
    line = result["segments"][0]
    assert line["fitted_end_ms"] == 998 and line["deviation_ms"] == -2
    assert line["warnings"] == ["clipped_at_track_end", "shorter_than_requested"]


def test_unknown_source_duration_and_empty_track():
    result = report([cue("a", 0, 1)], [1], 0, [cue("a", 0, 1)], 1)
    assert result["original_duration_ms"] is result["deviation_ms"] is None
    assert result["segments"][0]["deviation_ms"] == 0
    silent = report([], [], 2.0, [], 2.0)
    assert silent["segments"] == [] and silent["fitted_duration_ms"] == 2000
    assert silent["deviation_ms"] == 0


@pytest.mark.parametrize(
    "fitted",
    [
        [cue("other", 0, 1)],
        [cue("a", 0, 1), cue("a", 0, 1)],
        [cue("a", 1, 0)],
        [cue("a", 0, float("nan"))],
    ],
)
def test_bad_or_ambiguous_measurements_are_rejected(fitted):
    with pytest.raises(ValueError):
        report([cue("a", 0, 1)], [1], 1, fitted, 1)
