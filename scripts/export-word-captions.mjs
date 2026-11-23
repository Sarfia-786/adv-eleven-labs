import { readFileSync } from "node:fs";
import process from "node:process";
import { wordCaptionsToWebVtt } from "../examples/repo1/word-captions.mjs";

const usage = "Usage: node scripts/export-word-captions.mjs [result.json|-]";
const args = process.argv.slice(2);

if (args.length === 1 && args[0] === "--help") {
  console.log(usage);
} else if (args.length > 1) {
  console.error(usage);
  process.exitCode = 2;
} else {
  try {
    const source = args.length === 0 || args[0] === "-" ? 0 : args[0];
    const input = readFileSync(source, "utf8");
    let result;
    try {
      result = JSON.parse(input);
    } catch {
      throw new TypeError("Input must be valid JSON.");
    }
    process.stdout.write(wordCaptionsToWebVtt(result));
  } catch (error) {
    console.error(error.code ? "Could not read the caption input." : error.message);
    process.exitCode = 2;
  }
}
