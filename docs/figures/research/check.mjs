// Drives docs/research.html in a real Edge/Chrome (DevTools protocol) and checks every interaction and the console.
// Run from the repo root: node docs/figures/research/check.mjs
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const EDGE = ["C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", "C:/Program Files/Google/Chrome/Application/chrome.exe"]
  .find((p) => existsSync(p));
const PORT = 9333, url = pathToFileURL(resolve("docs/research.html")).href;
const proc = spawn(EDGE, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${PORT}`, "--user-data-dir=" + resolve(".taste-skill/cdp-profile"), "--window-size=1440,1000", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let tabs;
for (let i = 0; i < 50 && !tabs; i++) { try { tabs = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json(); } catch { await sleep(200); } }
const ws = new WebSocket(tabs.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const wait = new Map(); const errors = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && wait.has(d.id)) { wait.get(d.id)(d); wait.delete(d.id); }
  if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description ?? d.params.exceptionDetails.text);
  if (d.method === "Runtime.consoleAPICalled" && d.params.type === "error") errors.push("console.error: " + d.params.args.map((a) => a.value ?? a.description).join(" "));
};
const send = (method, params = {}) => new Promise((r) => { const i = ++id; wait.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }); if (r.result.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description); return r.result.result.value; };
await send("Runtime.enable"); await send("Page.enable");
await send("Page.navigate", { url }); await sleep(2500);

const results = []; const ok = (name, cond, got) => results.push([cond ? "PASS" : "FAIL", name, cond ? "" : JSON.stringify(got)]);
const click = (sel) => ev(`document.querySelector(${JSON.stringify(sel)}).click()`);
const text = (sel) => ev(`document.querySelector(${JSON.stringify(sel)})?.textContent ?? null`);
const count = (sel) => ev(`document.querySelectorAll(${JSON.stringify(sel)}).length`);
const setRange = (sel, v) => ev(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});e.value=${v};e.dispatchEvent(new Event('input',{bubbles:true}));})()`);

ok("data loaded", (await count("#stats li")) === 4, await count("#stats li"));
const odiaWer = await text("#odia-bars .brow:last-child .val");
await click('[data-m="cer"]'); const cer = await text("#odia-bars .brow:last-child .val");
ok("metric switch changes the bars", odiaWer !== cer, [odiaWer, cer]);
await click('[data-e="Whisper base"]');
ok("engine chip dims its bar", (await ev(`document.querySelector('#odia-bars .brow').classList.contains('off')`)) === true);
await click('[data-e="Whisper base"]');
await setRange("#strip-pick", 50);
ok("strip slider follows a clip", (await text("#strip-out")).includes("Clip 50"), await text("#strip-out"));
ok("strip shows 300 dots", (await count("#strips .dot")) === 300, await count("#strips .dot"));
const c1 = await text("#xp-out"); await click("#xp-next");
ok("explorer steps forward", c1 !== (await text("#xp-out")), [c1, await text("#xp-out")]);
await setRange("#xp-range", 7);
ok("explorer slider jumps", (await text("#xp-out")).startsWith("Clip 7 "), await text("#xp-out"));
ok("diff marks words", (await count("#xp-rows .w.bad")) > 0, await count("#xp-rows .w.bad"));
ok("Odia script is in the page", /[\u0B00-\u0B7F]/.test(await text("#xp-ref")), await text("#xp-ref"));
const chrf = await text("#tr-bars .brow:last-child .val"); await click('[data-t="bleu"]');
ok("translation score switch", chrf !== (await text("#tr-bars .brow:last-child .val")));
await setRange("#calc-min", 60);
ok("calculator updates", (await text("#calc-out")).startsWith("60 "), await text("#calc-out"));
ok("english plot has 4 dots", (await count("#plot .pt")) === 4, await count("#plot .pt"));
await click('[data-l="hindi"]'); ok("hindi plot has 2 dots", (await count("#plot .pt")) === 2, await count("#plot .pt"));
await click('[data-l="odia"]'); ok("odia plot has 3 dots", (await count("#plot .pt")) === 3, await count("#plot .pt"));
await click('[data-l="english"]'); await click('[data-h="fast"]');
ok("highlight marks exactly one engine", (await count("#plot .pt.hi")) === 1 && (await text("#pickline")).includes("fastest"), await text("#pickline"));
ok("silence section drawn", (await count("#si-kinds .krow")) > 3, await count("#si-kinds .krow"));
ok("real-speech panel drawn", (await text("#si-real-note")).includes("Does the guard"), await text("#si-real-note"));
ok("chart tables for screen readers", (await count("table.sr")) >= 6, await count("table.sr"));
const sample = await ev(`document.querySelector('#data-ml').getAttribute('data-sample')`);
ok("page uses REAL ml data (not the sample)", sample === "false", sample);
ok("no script errors", errors.length === 0, errors);

for (const [s, n, g] of results) console.log(s, n, g);
const bad = results.filter((r) => r[0] === "FAIL").length;
console.log(bad ? `\n${bad} FAILED` : "\nall passed");
ws.close(); proc.kill();
process.exit(bad ? 1 : 0);
