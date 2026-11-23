"""Offline acceptance for the pure multi-speaker dialogue request parser (#30)."""

import pytest
from pydantic import ValidationError

from services.hosted_dialogue_parser import (
    DialogueLimits,
    DialogueParseError,
    DialogueRequest,
    parse_dialogue,
    DialogueTurn,
    normalize_dialogue,
)

CAST = {"Alice": "profile-alice", "Bob": "profile-bob"}


def parsed(script=None, turns=None, voice_map=None, limits=None):
    payload = {"voice_map": CAST if voice_map is None else voice_map}
    if script is not None:
        payload["script"] = script
    if turns is not None:
        payload["turns"] = turns
    return normalize_dialogue(payload, limits=limits or DialogueLimits())


def test_text_and_structured_json_agree_with_repeated_speakers_and_punctuation():
    script = "Alice: Hello, Bob!\nBob: It's 10:30: are you ready?\nAlice: Yes: let's go."
    structured = [
        {"speaker_id": "Alice", "text": "Hello, Bob!"},
        {"speaker_id": "Bob", "text": "It's 10:30: are you ready?"},
        {"speaker_id": "Alice", "text": "Yes: let's go."},
    ]
    actual = parsed(script=script)
    assert actual == parsed(turns=structured)
    assert actual == parse_dialogue({"script": script, "voice_map": CAST})
    assert isinstance(actual, tuple)
    assert all(isinstance(turn, DialogueTurn) for turn in actual)
    assert [turn.speaker_id for turn in actual] == ["Alice", "Bob", "Alice"]
    assert [turn.text for turn in actual] == [turn["text"] for turn in structured]
    assert actual[1].text.count(":") == 2
    assert [turn.model_dump() for turn in actual] == structured


def test_bom_crlf_blank_lines_unicode_labels_and_spoken_punctuation():
    cast = {"李华": "voice-1", "ليلى": "voice-2"}
    script = '\ufeff李华: 你好！“你好吗？”\r\n\r\n  ليلى : رائع: حقاً؟  \r\n李华: 再见。\r\n'
    result = parsed(script=script, voice_map=cast)
    assert result == parsed(turns=[
        {"speaker_id": "李华", "text": "你好！“你好吗？”"},
        {"speaker_id": "ليلى", "text": "رائع: حقاً؟"},
        {"speaker_id": "李华", "text": "再见。"},
    ], voice_map=cast)
    assert result[1].text == "رائع: حقاً؟"
    assert result[-1].speaker_id == "李华"


def test_structured_turn_accepts_existing_speaker_alias_but_emits_speaker_id():
    turns = parsed(turns=[{"speaker": "Alice", "text": "Hi."},
                          {"speaker_id": "Bob", "text": "Hello."}])
    assert [item.model_dump() for item in turns] == [
        {"speaker_id": "Alice", "text": "Hi."},
        {"speaker_id": "Bob", "text": "Hello."},
    ]


@pytest.mark.parametrize("input_data,expected,line,turn", [
    ({"script": "Alice: Hello\n\nUnknown: Hello"}, "undeclared_speaker", 3, 2),
    ({"script": "Alice: Yes\nOops no label"}, "missing_speaker_label", 2, 2),
    ({"script": "Alice: hi\n: nothing"}, "invalid_speaker", 2, 2),
    ({"script": "Alice: hi\nBob:    "}, "empty_text", 2, 2),
    ({"turns": [{"speaker_id": "Alice", "text": "Yes"},
               {"speaker_id": "Unknown", "text": "No"}]}, "undeclared_speaker", None, 2),
    ({"turns": [{"speaker_id": "Alice", "text": "Yes"},
               {"speaker_id": "Bob", "text": " \t "}]}, "empty_text", None, 2),
])
def test_helpful_one_based_line_and_turn_locations(input_data, expected, line, turn):
    with pytest.raises(DialogueParseError) as e:
        normalize_dialogue({**input_data, "voice_map": CAST})
    assert e.value.detail() == {
        "code": expected, "line_number": line, "turn_index": turn,
    }
    assert expected in str(e.value)


@pytest.mark.parametrize("payload,expected", [
    ({"script": "", "voice_map": CAST}, "empty_dialogue"),
    ({"script": " \r\n\n  ", "voice_map": CAST}, "empty_dialogue"),
    ({"turns": [], "voice_map": CAST}, "empty_dialogue"),
    ({"voice_map": CAST}, "exactly_one_dialogue_source_required"),
    ({"script": "Alice: hi", "turns": [], "voice_map": CAST},
     "exactly_one_dialogue_source_required"),
])
def test_ambiguous_or_empty_input_is_denied(payload, expected):
    with pytest.raises(DialogueParseError) as e:
        normalize_dialogue(payload)
    assert e.value.code == expected


@pytest.mark.parametrize("voice_map", [
    {}, {"Alice": ""}, {" Alice": "a"}, {"Alice:": "a"},
    {"Alice": "  a  "}, {"Alice\nName": "profile"},
])
def test_invalid_or_unusable_voice_bindings_are_denied(voice_map):
    with pytest.raises(DialogueParseError, match="invalid_speaker_bindings"):
        parsed(script="Alice: Hi", voice_map=voice_map)


def test_can_build_typed_request_before_normalizing():
    request = DialogueRequest.model_validate({
        "voice_map": CAST,
        "turns": [{"speaker_id": "Bob", "text": "  Hello: Alice!  "}],
    })
    assert request.normalized_turns() == (DialogueTurn(speaker_id="Bob", text="Hello: Alice!"),)


@pytest.mark.parametrize("payload,index", [
    ({"turns": [{"speaker_id": "Alice", "text": 123}]}, 1),
    ({"turns": [{"speaker_id": "Alice", "text": "Hi"},
               {"speaker_id": "Bob", "text": None}]}, 2),
    ({"turns": [{"speaker_id": "Alice", "text": "Hi", "unexpected": 1}]}, 1),
])
def test_structured_schema_rejects_bad_turn_and_reports_index(payload, index):
    with pytest.raises(DialogueParseError) as e:
        normalize_dialogue({**payload, "voice_map": CAST})
    assert e.value.code == "invalid_request"
    assert e.value.turn_index == index


def test_pydantic_request_is_strict_and_rejects_extra_fields():
    with pytest.raises(ValidationError):
        DialogueRequest(script="Alice: hi", voice_map=CAST, unknown_key="not accepted")


@pytest.mark.parametrize("limits,script,expected", [
    (DialogueLimits(max_script_chars=9), "Alice: Hello", "script_too_long"),
    (DialogueLimits(max_turns=1), "Alice: one\nBob: two", "too_many_turns"),
    (DialogueLimits(max_turn_chars=3), "Alice: Four", "turn_too_long"),
    (DialogueLimits(max_spoken_chars=6), "Alice: yes\nBob: yup!", "spoken_text_too_long"),
    (DialogueLimits(max_speakers=1), "Alice: hi", "invalid_speaker_bindings"),
    (DialogueLimits(max_speaker_chars=3), "Alice: hi", "invalid_speaker_bindings"),
])
def test_configured_limits_are_enforced_on_labeled_scripts(limits, script, expected):
    with pytest.raises(DialogueParseError) as e:
        parsed(script=script, limits=limits)
    assert e.value.code == expected


def test_structured_limits_match_script_limits_and_index_offending_turn():
    limits = DialogueLimits(max_turns=2, max_turn_chars=4, max_spoken_chars=6)
    with pytest.raises(DialogueParseError) as e:
        parsed(turns=[{"speaker": "Alice", "text": "Hi"},
                      {"speaker": "Bob", "text": "12345"}], limits=limits)
    assert (e.value.code, e.value.turn_index) == ("turn_too_long", 2)
    with pytest.raises(DialogueParseError) as e:
        parsed(turns=[{"speaker": "Alice", "text": "ABC"},
                      {"speaker": "Bob", "text": "DEFG"}], limits=limits)
    assert (e.value.code, e.value.turn_index) == ("spoken_text_too_long", 2)
    with pytest.raises(DialogueParseError) as e:
        parsed(turns=[{"speaker": "Alice", "text": "a"}] * 3, limits=limits)
    assert (e.value.code, e.value.turn_index) == ("too_many_turns", 3)


@pytest.mark.parametrize("field", ["max_script_chars", "max_turns", "max_speakers",
                                  "max_speaker_chars", "max_turn_chars", "max_spoken_chars"])
def test_limits_reject_nonpositive_values(field):
    with pytest.raises(ValueError, match="positive integers"):
        DialogueLimits(**{field: 0})


def test_unlabeled_continuation_is_not_silently_spoken_as_previous_speaker():
    with pytest.raises(DialogueParseError) as e:
        parsed(script="Alice: Hello.\n  A dangerous unlabelled continuation.")
    assert (e.value.code, e.value.line_number) == ("missing_speaker_label", 2)


def test_import_is_independent_of_inference_services():
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1] / "backend"
    code = (
        "import services.hosted_dialogue_parser, sys; "
        "assert 'services.dub_mix' not in sys.modules; "
        "assert 'services.tts_backend' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], check=False,
                            capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": str(backend)})
    assert result.returncode == 0, result.stderr
