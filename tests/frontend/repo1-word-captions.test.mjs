import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { wordCaptionsToWebVtt } from "../../examples/repo1/word-captions.mjs";

const cli = fileURLToPath(new URL("../../scripts/export-word-captions.mjs", import.meta.url));
const entry = (word, start_ms, end_ms) => ({ word, start_ms, end_ms });

test("keeps leading silence, gaps, repeated words and millisecond boundaries", () => {
  const result = { duration_ms: 630, words: [entry("yes", 80, 110), entry("yes", 160, 630)] };
  assert.equal(wordCaptionsToWebVtt(result),
    "WEBVTT\n\n00:00:00.080 --> 00:00:00.110\nyes\n\n00:00:00.160 --> 00:00:00.630\nyes\n\n");
});

test("retains Unicode and escapes literal WebVTT cue markup", () => {
  const track = { duration_ms: 2, words: [entry("হ্যালো", 0, 1), entry("<b>A&B</b>-->", 1, 2)] };
  assert.equal(wordCaptionsToWebVtt(track),
    "WEBVTT\n\n00:00:00.000 --> 00:00:00.001\nহ্যালো\n\n00:00:00.001 --> 00:00:00.002\n&lt;b&gt;A&amp;B&lt;/b&gt;--&gt;\n\n");
});

test("emits an empty track for an empty alignment", () => {
  assert.equal(wordCaptionsToWebVtt({ duration_ms: 0, words: [] }), "WEBVTT\n\n");
});

test("carries across hour boundaries without wrapping at 24 hours", () => {
  const out = wordCaptionsToWebVtt({ duration_ms: 90000001, words: [entry("tick", 3599999, 3600000), entry("end", 90000000, 90000001)] });
  assert.match(out, /00:59:59\.999 --> 01:00:00\.000/);
  assert.match(out, /25:00:00\.000 --> 25:00:00\.001/);
});

test("rejects malformed results, reversed, fractional or overlapping intervals", () => {
  const malformed = [
    null, {}, { words: [], duration_ms: -1 }, { words: {}, duration_ms: 20 },
    { words: [], duration_ms: Number.MAX_SAFE_INTEGER + 1 },
    ...[entry("x", -1, 2), entry("x", 2, 2), entry("x", 2, 1),
        entry("x", 1.5, 4), entry("x", 0, 21), entry("x", "1", 2), null]
      .map((word) => ({ duration_ms: 20, words: [word] })),
    { duration_ms: 20, words: [entry("first", 0, 15), entry("second", 10, 20)] },
  ];
  for (const result of malformed) assert.throws(() => wordCaptionsToWebVtt(result));
});

test("rejects cue breaks and malformed text with only an index in the diagnostic", () => {
  for (const word of ["", "  ", null, 5, "private\n\nNOTE private", "private\rnext", "\u0000", "\ud800"]) {
    assert.throws(() => wordCaptionsToWebVtt({ duration_ms: 3, words: [entry(word, 0, 3)] }),
      (error) => error instanceof TypeError && error.message.includes("words[0]") && !error.message.includes("private"));
  }
});

test("CLI exports identical UTF-8 from a file, stdin and explicit dash", () => {
  const directory = mkdtempSync(join(tmpdir(), "voice-captions-"));
  try {
    const path = join(directory, "result with spaces.json");
    const result = { duration_ms: 100, words: [entry("café", 1, 100)] };
    const input = JSON.stringify(result);
    writeFileSync(path, input);
    for (const args of [[path], [], ["-"]]) {
      const run = spawnSync(process.execPath, [cli, ...args], { input, encoding: "utf8" });
      assert.equal(run.status, 0, run.stderr);
      assert.equal(run.stdout, wordCaptionsToWebVtt(result));
      assert.equal(run.stderr, "");
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("CLI reports invalid JSON or late errors without writing partial cues or scripts", () => {
  const late = { duration_ms: 20, words: [entry("PRIVATE", 0, 10), entry("SECRET", 5, 15)] };
  for (const input of ["{PRIVATE", JSON.stringify(late)]) {
    const run = spawnSync(process.execPath, [cli], { input, encoding: "utf8" });
    assert.equal(run.status, 2);
    assert.equal(run.stdout, "");
    assert.ok(run.stderr.trim());
    assert.doesNotMatch(run.stderr, /PRIVATE|SECRET/);
  }
});

test("CLI shows help and rejects extra arguments and missing files", () => {
  const help = spawnSync(process.execPath, [cli, "--help"], { encoding: "utf8" });
  assert.equal(help.status, 0);
  assert.match(help.stdout, /Usage:/);
  for (const args of [["one", "two"], [join(tmpdir(), "no-caption-" + randomUUID())]]) {
    const run = spawnSync(process.execPath, [cli, ...args], { encoding: "utf8" });
    assert.equal(run.status, 2);
    assert.equal(run.stdout, "");
  }
});
