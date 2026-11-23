# Hosted dialogue input contract (#30)

The pure parser is `backend/services/hosted_dialogue_parser.py`. It prepares a
future hosted multi-speaker submission without creating jobs, looking up user
voices, synthesizing audio, mixing tracks, or reading the database. It is an
independent precursor to [#17](https://github.com/Sarfia-786/adv-eleven-labs/issues/17).

## Accepted inputs

Exactly one of `script` or `turns` is required. Both use the **same** `voice_map`,
which follows the existing audiobook contract: the map keys are human-facing
speaker labels and values are voice **profile IDs**, not audio files or grants.
The normalized turns use `speaker_id`, as existing dub segments do. The parser
requires every spoken speaker to be declared; it does **not** authorize access
to a profile or check that the requester owns that voice. The authenticated
future #17 service must enforce tenant ownership and plan entitlement.

Labeled script:

```json
{
  "script": "Alice: Hello, Bob!\nBob: It is 10:30: shall we start?\nAlice: Yes!",
  "voice_map": {
    "Alice": "alice-profile-id",
    "Bob": "bob-profile-id"
  }
}
```

Equivalent structured turns:

```json
{
  "turns": [
    {"speaker_id": "Alice", "text": "Hello, Bob!"},
    {"speaker_id": "Bob", "text": "It is 10:30: shall we start?"},
    {"speaker_id": "Alice", "text": "Yes!"}
  ],
  "voice_map": {
    "Alice": "alice-profile-id",
    "Bob": "bob-profile-id"
  }
}
```

The structured form also accepts `speaker` as an input alias for `speaker_id`,
but normalization emits only `speaker_id`. Output is a tuple of typed
`DialogueTurn(speaker_id, text)` records in original order. Repeating a speaker
does not merge turns. The text parser splits at the **first** colon on each
nonblank physical line; all later colons and spoken punctuation remain in the
text. Leading/trailing whitespace is removed, blank lines are skipped, and
UTF-8 BOM, CRLF, CR and Unicode speaker names are supported. Every nonblank
line must begin with a declared `Speaker name:` label; unlabeled continuation
lines are errors rather than silently changing whose voice speaks.

## Entry points and limits

```python
from services.hosted_dialogue_parser import DialogueRequest, parse_dialogue

request = DialogueRequest.model_validate(payload)
turns = parse_dialogue(request)
# Once #17 is implemented, resolve each request.voice_map[speaker_id]
# against the authenticated tenant BEFORE submitting synthesis jobs.
```

`DialogueRequest` is a strict Pydantic v2 typed payload, and `parse_dialogue`
returns canonical ordered `DialogueTurn` models. Defaults are set by
`DialogueLimits`: 50,000 script characters; 200 turns; 16 declared speakers;
128 characters per speaker label; 4,000 characters per turn; and 40,000 total
spoken characters. Server callers can pass a smaller or different
`DialogueLimits(...)` to enforce a configured input policy. These lengths
count Python Unicode code points, not bytes. The client cannot raise them by
putting limit fields in its request.

Errors are `DialogueParseError` with stable `code`, one-based `line_number`
for malformed script lines, and/or one-based `turn_index` for an offending
turn (available in `.detail()`). Invalid source selection, input limits,
undeclared speaker names, missing labels, bad bindings, empty text, malformed
JSON turns, and excess size are rejected before any side effects. A later
FastAPI route can map `.detail()` to a 422 response without exposing raw input.

## Verification

```sh
PYTHONPATH=backend python -m pytest -q tests/test_hosted_dialogue_parser.py
```

Tests cover text/JSON parity across three repeated-speaker turns, spoken
colons, Unicode labels, blank lines, stable ordering, undeclared speakers,
empty input and text, invalid binding maps, malformed structured turns,
line/turn error coordinates, and all configured input limits. The tests need
no model weights, database, GPU, or network access.
