"""Hosted subscription policy. Engine availability is checked separately."""

from enum import Enum


class Plan(str, Enum):
    FREE = "free"
    PREMIUM = "premium"


class Capability(str, Enum):
    BASIC_SPEECH = "basic_speech"
    INSTANT_CLONING = "instant_cloning"
    CLOUD_VOICE_PROFILES = "cloud_voice_profiles"
    EXPRESSIVE_CONTROLS = "expressive_controls"
    MULTI_SPEAKER = "multi_speaker"
    WORD_TIMESTAMPS = "word_timestamps"
    PREMIUM_MASTERING = "premium_mastering"
    AUTO_DUBBING = "auto_dubbing"
    PRIORITY_QUEUE = "priority_queue"
    WEBHOOKS = "webhooks"


_FREE = frozenset({Capability.BASIC_SPEECH})
_BY_PLAN = {
    Plan.FREE: _FREE,
    Plan.PREMIUM: _FREE
    | {
        Capability.INSTANT_CLONING,
        Capability.CLOUD_VOICE_PROFILES,
        Capability.EXPRESSIVE_CONTROLS,
        Capability.MULTI_SPEAKER,
        Capability.WORD_TIMESTAMPS,
        Capability.PREMIUM_MASTERING,
        Capability.AUTO_DUBBING,
        Capability.PRIORITY_QUEUE,
        Capability.WEBHOOKS,
    },
}


def capabilities_for(plan: Plan) -> frozenset[Capability]:
    return _BY_PLAN[plan]
