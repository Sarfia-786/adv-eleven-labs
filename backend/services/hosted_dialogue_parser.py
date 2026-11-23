"""Pure, bounded dialogue input normalization for future hosted submission (#30).

This module never loads models, looks up profiles, or accesses persistence. The
caller is responsible for authenticating the profile IDs in `voice_map`.
`speaker_id` matches dubbing's segment key, while `voice_map` matches the
existing audiobook cast mapping (speaker label -> voice profile ID).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError


@dataclass(frozen=True)
class DialogueLimits:
    max_script_chars: int = 50_000
    max_turns: int = 200
    max_speakers: int = 16
    max_speaker_chars: int = 128
    max_turn_chars: int = 4_000
    max_spoken_chars: int = 40_000

    def __post_init__(self) -> None:
        if any(
            type(getattr(self, key)) is not int or getattr(self, key) < 1
            for key in self.__dataclass_fields__
        ):
            raise ValueError("Dialogue limits must be positive integers")


DEFAULT_LIMITS = DialogueLimits()


class DialogueParseError(ValueError):
    """User-correctable error with one-based line and/or turn coordinates."""

    def __init__(
        self,
        code: str,
        *,
        line_number: int | None = None,
        turn_index: int | None = None,
    ) -> None:
        self.code = code
        self.line_number = line_number
        self.turn_index = turn_index
        location = (
            f" on line {line_number}" if line_number is not None else
            f" at turn {turn_index}" if turn_index is not None else ""
        )
        super().__init__(f"{code}{location}")

    def detail(self) -> dict[str, str | int | None]:
        return {
            "code": self.code,
            "line_number": self.line_number,
            "turn_index": self.turn_index,
        }


class DialogueTurn(BaseModel):
    """Canonical, ordered spoken turn; accepts legacy `speaker` as an alias."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    speaker_id: str = Field(validation_alias=AliasChoices("speaker_id", "speaker"))
    text: str


class DialogueRequest(BaseModel):
    """Exactly one script or JSON turn list plus declared speaker/voice bindings.

    `voice_map` identifies requested voice profiles; resolving profile access
    is intentionally the responsibility of the later authenticated submission.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    script: str | None = None
    turns: list[DialogueTurn] | None = None
    voice_map: dict[str, str]

    def normalized_turns(
        self, *, limits: DialogueLimits = DEFAULT_LIMITS
    ) -> tuple[DialogueTurn, ...]:
        return normalize_dialogue(self, limits=limits)


def _check_bindings(voice_map: Mapping[str, str], limits: DialogueLimits) -> None:
    if not voice_map or len(voice_map) > limits.max_speakers:
        raise DialogueParseError("invalid_speaker_bindings")
    for name, profile in voice_map.items():
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or len(name) > limits.max_speaker_chars
            or ":" in name
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in name)
            or not isinstance(profile, str)
            or not profile.strip()
            or profile != profile.strip()
            or len(profile) > 200
        ):
            raise DialogueParseError("invalid_speaker_bindings")


def _check_turn(
    speaker: str,
    text: str,
    *,
    declared: Mapping[str, str],
    limits: DialogueLimits,
    turn_index: int,
    line_number: int | None,
) -> DialogueTurn:
    where = {"turn_index": turn_index, "line_number": line_number}
    if not speaker or speaker != speaker.strip() or len(speaker) > limits.max_speaker_chars:
        raise DialogueParseError("invalid_speaker", **where)
    if speaker not in declared:
        raise DialogueParseError("undeclared_speaker", **where)
    spoken = text.strip()
    if not spoken:
        raise DialogueParseError("empty_text", **where)
    if len(spoken) > limits.max_turn_chars:
        raise DialogueParseError("turn_too_long", **where)
    if any((ord(ch) < 32 and ch not in "\t") or ord(ch) == 127 for ch in spoken):
        raise DialogueParseError("invalid_text", **where)
    return DialogueTurn(speaker_id=speaker, text=spoken)


def _script_turns(
    script: str, voice_map: Mapping[str, str], limits: DialogueLimits
) -> tuple[DialogueTurn, ...]:
    if len(script) > limits.max_script_chars:
        raise DialogueParseError("script_too_long")
    result: list[DialogueTurn] = []
    spoken_chars = 0
    # Split on physical lines only; Unicode punctuation and speaker names are
    # left intact. Split at the FIRST colon to preserve colons in speech.
    lines = script.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line_number, raw in enumerate(lines, start=1):
        line = (raw.lstrip("\ufeff") if line_number == 1 else raw).strip()
        if not line:
            continue
        turn_index = len(result) + 1
        if turn_index > limits.max_turns:
            raise DialogueParseError("too_many_turns", line_number=line_number,
                                     turn_index=turn_index)
        speaker, separator, text = line.partition(":")
        if not separator:
            raise DialogueParseError("missing_speaker_label", line_number=line_number,
                                     turn_index=turn_index)
        turn = _check_turn(speaker.strip(), text, declared=voice_map, limits=limits,
                           turn_index=turn_index, line_number=line_number)
        spoken_chars += len(turn.text)
        if spoken_chars > limits.max_spoken_chars:
            raise DialogueParseError("spoken_text_too_long", line_number=line_number,
                                     turn_index=turn_index)
        result.append(turn)
    if not result:
        raise DialogueParseError("empty_dialogue")
    return tuple(result)


def _structured_turns(
    turns: list[DialogueTurn], voice_map: Mapping[str, str], limits: DialogueLimits
) -> tuple[DialogueTurn, ...]:
    if not turns:
        raise DialogueParseError("empty_dialogue")
    if len(turns) > limits.max_turns:
        raise DialogueParseError("too_many_turns", turn_index=limits.max_turns + 1)
    result = []
    spoken_chars = 0
    for index, raw in enumerate(turns, start=1):
        turn = _check_turn(raw.speaker_id.strip(), raw.text, declared=voice_map,
                           limits=limits, turn_index=index, line_number=None)
        spoken_chars += len(turn.text)
        if spoken_chars > limits.max_spoken_chars:
            raise DialogueParseError("spoken_text_too_long", turn_index=index)
        result.append(turn)
    return tuple(result)


def normalize_dialogue(
    request: DialogueRequest | Mapping[str, Any],
    *,
    limits: DialogueLimits = DEFAULT_LIMITS,
) -> tuple[DialogueTurn, ...]:
    """Validate a typed/JSON request and return speaker turns in source order.

    Raises `DialogueParseError` on any invalid input. The caller can pass
    ".detail()" straight to a structured 422 response in the future route.
    """
    if not isinstance(request, DialogueRequest):
        try:
            request = DialogueRequest.model_validate(request)
        except ValidationError as exc:
            location = exc.errors()[0]["loc"]
            turn_index = next(
                (part + 1 for pos, part in enumerate(location)
                 if isinstance(part, int) and pos and location[pos - 1] == "turns"),
                None,
            )
            raise DialogueParseError("invalid_request", turn_index=turn_index) from None
    has_script = request.script is not None
    has_turns = request.turns is not None
    if has_script == has_turns:
        raise DialogueParseError("exactly_one_dialogue_source_required")
    _check_bindings(request.voice_map, limits)
    if has_script:
        assert request.script is not None
        return _script_turns(request.script, request.voice_map, limits)
    assert request.turns is not None
    return _structured_turns(request.turns, request.voice_map, limits)


def parse_dialogue(
    request: DialogueRequest | Mapping[str, Any],
    *,
    limits: DialogueLimits = DEFAULT_LIMITS,
) -> tuple[DialogueTurn, ...]:
    """Named pure entry point for callers preparing hosted dialogue submission."""
    return normalize_dialogue(request, limits=limits)
