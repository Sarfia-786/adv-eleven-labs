# Export aligned words to WebVTT

Repo 1 can display one word at a time over a final audio track by exporting its measured word timings to a WebVTT file. The converter reads a local JSON result and runs offline. It also works as an ES module in a browser. The production of aligned words is tracked in [issue #16](https://github.com/Sarfia-786/adv-eleven-labs/issues/16).

## Command line

From the repository root, run the following with Node.js 22 or later. Both forms write UTF-8 WebVTT to standard output.

```sh
node scripts/export-word-captions.mjs result.json > captions.vtt
node scripts/export-word-captions.mjs < result.json > captions.vtt
```

The input uses the duration of the delivered track and absolute word boundaries in integer milliseconds. Additional generation metadata may be present.

```json
{
  "duration_ms": 1000,
  "words": [
    {"word": "Hello", "start_ms": 120, "end_ms": 480},
    {"word": "again", "start_ms": 540, "end_ms": 940}
  ]
}
```

```vtt
WEBVTT

00:00:00.120 --> 00:00:00.480
Hello

00:00:00.540 --> 00:00:00.940
again
```

## Application use

```js
import { wordCaptionsToWebVtt } from "./examples/repo1/word-captions.mjs";

const track = new Blob([wordCaptionsToWebVtt(result)], { type: "text/vtt" });
```

Use one ordered, nonoverlapping word stream per track. Intervals may touch. Gaps and repeated words are preserved. Word text must fit on one line. Characters such as `<` and `&` are displayed literally. An empty alignment produces a valid empty track. Overlapping speakers require separate input tracks.

The converter validates the whole result before emitting any cues. Bad JSON, invalid intervals or unreadable input produce an error on standard error and exit status 2. Errors identify the offending word by index without repeating its text. Run the tests with `node --test tests/frontend/repo1-word-captions.test.mjs`.
