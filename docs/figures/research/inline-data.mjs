// Inlines docs/data/odia-research.json and docs/data/ml-research.json into docs/research.html, so the page works from
// file:// and over http (fetch() cannot read local files). Run from the repo root: node docs/figures/research/inline-data.mjs
// The ML numbers are checked first: a benchmark run with a broken pipeline (empty transcripts) is refused, and the page
// falls back to the clearly-labelled sample file instead of showing wrong measurements.
import { readFileSync, writeFileSync, existsSync } from "node:fs";

const read = (p) => JSON.parse(readFileSync(p, "utf8"));
const odia = read("docs/data/odia-research.json");
const REAL = "docs/data/ml-research.json", SAMPLE = "docs/figures/research/sample-ml-research.json", CLIPS = "docs/figures/research/odia-clips.json";

function problems(ml) {
  const bad = [];
  // English models make well under 45% word errors on read speech; a broken pipeline that writes nothing shows ~70-100%.
  // Hindi is genuinely hard for small Whisper models (high 80s is real), so only an all-empty run (100%) is refused.
  const LIMIT = { english: 45, hindi: 99.5 };
  for (const k of ["english", "hindi"]) {
    for (const [name, e] of Object.entries(ml[k]?.engines ?? {})) {
      if (!(e.wer >= 0 && e.wer < LIMIT[k])) bad.push(`${k} ${name}: word error ${e.wer}% is implausible (empty transcripts?)`);
    }
    if (!Object.keys(ml[k]?.engines ?? {}).length) bad.push(`${k}: no engines`);
  }
  // Per-clip Odia text: the corrected file (odia-clips.py) wins. The benchmark's own odia_clips is only usable if the
  // engines really differ: since v1.1.8 "Whisper on Odia" through Transcriber returns the Odia engine's text again.
  if (!existsSync(CLIPS)) {
    const clips = ml.odia_clips ?? [];
    const empty = clips.filter((c) => !c.engines?.["OpenFlow Odia"]?.trim()).length;
    const same = clips.filter((c) => c.engines?.["Whisper base"] === c.engines?.["OpenFlow Odia"]).length;
    if (clips.length < 10 || empty > clips.length * 0.2) bad.push(`odia_clips: ${empty} of ${clips.length} OpenFlow Odia transcripts are empty`);
    if (same > clips.length * 0.5) bad.push(`odia_clips: Whisper and OpenFlow Odia wrote identical text for ${same} of ${clips.length} clips (run docs/figures/research/odia-clips.py)`);
  }
  const s = ml.silence;
  if (!s || s.recordings < 10 || !s.before || !s.after) bad.push("silence: missing");
  return bad;
}

let ml, sample = false;
if (existsSync(REAL)) {
  ml = read(REAL);
  const bad = problems(ml);
  if (bad.length) {
    console.warn("REFUSED docs/data/ml-research.json:\n  - " + bad.join("\n  - ") + "\nUsing the sample file; the page shows a placeholder banner.");
    ml = read(SAMPLE); sample = true;
  }
} else { console.warn("docs/data/ml-research.json not found; using the sample file."); ml = read(SAMPLE); sample = true; }

const clips = existsSync(CLIPS) && !sample ? read(CLIPS) : ml.odia_clips;
const json = (o) => JSON.stringify(o).replace(/</g, "\u003c").replace(/\u2028|\u2029/g, " ");
const block = `<!-- DATA:BEGIN (written by docs/figures/research/inline-data.mjs; do not edit by hand) -->
<script type="application/json" id="data-odia">${json(odia)}</script>
<script type="application/json" id="data-ml" data-sample="${sample}">${json(ml)}</script>
<script type="application/json" id="data-clips">${json(clips)}</script>
<!-- DATA:END -->`;
const html = readFileSync("docs/research.html", "utf8");
const out = html.replace(/<!-- DATA:BEGIN[\s\S]*?<!-- DATA:END -->/, () => block);
if (out === html && !html.includes("DATA:BEGIN")) throw new Error("markers missing in docs/research.html");
writeFileSync("docs/research.html", out);
console.log(sample ? "inlined SAMPLE ml data (placeholders)" : "inlined real ml data");
