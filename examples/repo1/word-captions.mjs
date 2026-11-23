// Convert Repo 1's final-track alignment to a single WebVTT word track.

function timestamp(ms) {
  const millis = ms % 1000;
  const seconds = (ms - millis) / 1000;
  const hours = Math.floor(seconds / 3600);
  const pad = (value, width) => String(value).padStart(width, "0");
  return `${pad(hours, 2)}:${pad(Math.floor(seconds / 60) % 60, 2)}:${pad(seconds % 60, 2)}.${pad(millis, 3)}`;
}

export function wordCaptionsToWebVtt(result) {
  if (!Number.isSafeInteger(result?.duration_ms) || result.duration_ms < 0 || !Array.isArray(result.words)) {
    throw new TypeError("Expected duration_ms in whole milliseconds and a words array.");
  }

  let previousEnd = 0;
  const lines = ["WEBVTT", ""];
  for (const [index, entry] of result.words.entries()) {
    const { word, start_ms: start, end_ms: end } = entry ?? {};
    if (typeof word !== "string" || !word.trim() || !word.isWellFormed() || /[\u0000-\u001f\u007f-\u009f\u2028\u2029]/u.test(word)) {
      throw new TypeError(`words[${index}].word must be nonempty, single-line Unicode text.`);
    }
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < previousEnd || end <= start || end > result.duration_ms) {
      throw new RangeError(`words[${index}] needs an ordered, positive interval within duration_ms.`);
    }

    const text = word.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
    lines.push(`${timestamp(start)} --> ${timestamp(end)}`, text, "");
    previousEnd = end;
  }
  return lines.join("\n") + "\n";
}
