// "How OpenFlow hears Odia": a bench with a desk microphone, three modules and a laptop, all on one plate.
// node docs/figures/odia-desk/build.mjs [--light]  -> odia-desk.html (standalone, for checks)
//                                                 -> injects the figure into docs/index.html between its markers
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as k from "../kit/iso-kit.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const theme = process.argv.includes("--light") ? "light" : "dark";

// Truth: the numbers the figure shows come from docs/data/odia-research.json (research_odia.py).
const R = JSON.parse(readFileSync(process.env.OF_RESEARCH || join(HERE, "..", "..", "data", "odia-research.json"), "utf-8"));
const ODIA_MS = R.asr["OpenFlow Odia"].ms_per_clip;
const PHRASE = { or: "ମୁଁ ଆଜି ଅଫିସ ଆସିପାରିବି ନାହିଁ", en: "I can't come to the office today" };

const WIDTH = 760;
const HEIGHT = 360;

const PLATE = { x: -176, y: -58, w: 380, d: 124, r: 10 };
const PLATE_H = 10;
const FOOT_H = 5;

const MIC = [-146, -8];
const MIC_BASE_R = 16;
const MIC_Z = 66;
const MIC_TOP = 96;

const GATE = { x: -112, y: -22, w: 36, d: 44, r: 3 };
const GATE_H = 26;
const FLAP = { x: -103, y: -2.2, w: 18, d: 2.4, r: 0.8 };

const READ = { x: -64, y: -28, w: 66, d: 54, r: 4 };
const READ_H = 18;
const DRUM = [-34, -2];
const DRUM_R = 17;
const DRUM_TOP = READ_H + 24;

const XLAT = { x: 22, y: -24, w: 44, d: 42, r: 3 };
const XLAT_H = 22;
const PIVOT = [46, -6];

const LAP = { x: 92, y: -42, w: 100, d: 60, r: 4 };
const LAP_H = 4;
const SCR = { x0: 96, x1: 188, y: -40, z0: LAP_H + 2, z1: LAP_H + 58, t: 3 };
const GLASS = { x0: SCR.x0 + 4, x1: SCR.x1 - 4, z0: SCR.z0 + 5, z1: SCR.z1 - 4 };

const TAPE = { x: 2, y: 30, w: 92, d: 7, r: 1 };

const P = k.fitProjection(
  [...k.boxCorners(PLATE, -PLATE_H - FOOT_H, 0), [MIC[0], MIC[1], MIC_TOP + 4], [SCR.x1, SCR.y, SCR.z1], [SCR.x0, SCR.y, SCR.z1]],
  WIDTH,
  HEIGHT,
  { pad: 10, azimuth: 60 },
);

const at = (point) => k.iso(point, P);
const S = (paths, style) => k.solidSvg(paths, style);
const L = (d, style) => k.lineSvg(d, style);
const D = (points, style) => k.dotsSvg(points, style);
const byDepth = (points) => [...points].sort((a, b) => k.depthOf([a[0], a[1], 0], P) - k.depthOf([b[0], b[1], 0], P));
const planeOf = (y) => k.sideMatrix([0, y], 0, P, "left");
const rectIn = (x0, z0, x1, z1, r) => k.pathOf(k.roundedPlan({ x: x0, y: z0, w: x1 - x0, d: z1 - z0, r }, 5).map(([u, z]) => [u, -z]), true);

function labelPlate(plan, z, lines) {
  const out = [S(k.slabOf(plan, z, 0.6, P, 3), { tone: "lo", crease: "none" })];
  out.push(L(lines.map((w, i) => k.lineOnTop([plan.x + 2.5, plan.y + 2.4 + i * 2.2], [plan.x + 2.5 + w, plan.y + 2.4 + i * 2.2], z + 0.6, P)).join(""), { tone: "lo", free: true }));
  out.push(D([at([plan.x + plan.w - 2.2, plan.y + plan.d / 2, z + 0.6])], { size: 0.4 }));
  return out.join("");
}

function frontPlate(x0, x1, z0, z1, y, text) {
  // engraved name plate on a front face, two screws, the module's name in the plane
  return [
    `<g transform="${planeOf(y)}">`,
    `<path class="iso-line" data-tone="lo" d="${rectIn(x0, z0, x1, z1, 1)}"/>`,
    `<circle class="iso-wire-end" cx="${x0 + 2}" cy="${-(z0 + z1) / 2}" r="0.55"/><circle class="iso-wire-end" cx="${x1 - 2}" cy="${-(z0 + z1) / 2}" r="0.55"/>`,
    `<text class="iso-face-text" data-tone="mid" x="${(x0 + x1) / 2}" y="${-(z0 + z1) / 2 + 1.2}" font-size="3.3" text-anchor="middle">${text}</text>`,
    `</g>`,
  ].join("");
}

function plate() {
  const out = [`<path class="iso-halo" d="${k.haloOf(PLATE, -PLATE_H - FOOT_H, PLATE_H, P)}"/>`];
  for (const [x, y] of byDepth(k.corners(PLATE, 24))) {
    out.push(S(k.cylinder(x, y, 7, -PLATE_H - FOOT_H, 1.6, P, 28), { tone: "lo" }));
    out.push(S(k.cylinder(x, y, 5.4, -PLATE_H - FOOT_H + 1.6, FOOT_H - 1.6, P, 28), { tone: "mid" }));
  }
  out.push(S(k.slabOf(PLATE, -PLATE_H, PLATE_H, P, 8, 1.6), { tone: "mid" }));
  out.push(L(k.planOutline(k.insetPlan(PLATE, 5), 0, P), { tone: "lo" }));
  const screws = k.corners(PLATE, 10);
  out.push(L(screws.map(([x, y]) => k.ring(x, y, 2.2, 0, P, 16)).join(""), { tone: "lo" }));
  out.push(D(screws.map(([x, y]) => at([x, y, 0])), { size: 0.5 }));
  // ruler strip along the front edge
  const strip = { x: -160, y: PLATE.y + PLATE.d - 14, w: 140, d: 7, r: 1 };
  out.push(S(k.slabOf(strip, 0, 0.6, P, 3), { tone: "lo", crease: "none" }));
  const ticks = k.topTicks(strip.x + 4, strip.x + strip.w - 4, 4, 5, strip.y + 0.8, 0.6, [2, 3.6], P);
  out.push(L(ticks.minor, { tone: "lo" }), L(ticks.major, { tone: "mid" }));
  out.push(D([at([strip.x + 2, strip.y + 3.5, 0.6]), at([strip.x + strip.w - 2, strip.y + 3.5, 0.6])], { size: 0.45 }));
  // name plate: OPENFLOW · ON-DEVICE
  const name = { x: 130, y: PLATE.y + PLATE.d - 16, w: 52, d: 9, r: 1.2 };
  out.push(S(k.slabOf(name, 0, 0.8, P, 3), { tone: "lo", crease: "none" }));
  out.push(k.faceTextSvg(k.topMatrix([name.x + name.w / 2, name.y + 6], 0.8, P, "x"), "OPENFLOW · ON-DEVICE", { size: 3, tone: "mid", anchor: "middle" }));
  out.push(D([at([name.x + 2.4, name.y + name.d / 2, 0.8]), at([name.x + name.w - 2.4, name.y + name.d / 2, 0.8])], { size: 0.4 }));
  return out.join("");
}

function tape() {
  // the printed tape runs along the bench, from the reader's exit roller to the laptop
  const out = [S(k.slabOf(TAPE, 0, 0.5, P, 3), { tone: "hi", crease: "none" })];
  out.push(L(k.lineOnTop([TAPE.x, TAPE.y + 1], [TAPE.x + TAPE.w, TAPE.y + 1], 0.5, P) + k.lineOnTop([TAPE.x, TAPE.y + TAPE.d - 1], [TAPE.x + TAPE.w, TAPE.y + TAPE.d - 1], 0.5, P), { tone: "faint" }));
  // tape guides: two posts that hold the tape where it passes the translator
  for (const x of [20, 70]) {
    out.push(S(k.cylinder(x, TAPE.y - 2, 1.6, 0, 5, P, 14), { tone: "mid" }));
    out.push(S(k.cylinder(x, TAPE.y + TAPE.d + 2, 1.6, 0, 5, P, 14), { tone: "mid" }));
  }
  return out.join("");
}

function microphone() {
  const [x, y] = MIC;
  const out = [`<path class="iso-halo" d="${k.haloOf({ x: x - MIC_BASE_R, y: y - MIC_BASE_R, w: MIC_BASE_R * 2, d: MIC_BASE_R * 2, r: MIC_BASE_R }, 0, 2, P)}" style="filter:blur(3px)"/>`];
  out.push(S(k.cylinder(x, y, MIC_BASE_R, 0, 3, P, 48, 0.8), { tone: "mid" }));
  out.push(S(k.cylinder(x, y, MIC_BASE_R - 3, 3, 3, P, 48, 0.6), { tone: "mid" }));
  out.push(L(k.knurl(x, y, MIC_BASE_R - 3, 3, 6, 56, P), { tone: "faint" }));
  out.push(L(k.ring(x, y, MIC_BASE_R - 6, 6, P, 40), { tone: "lo" }));
  out.push(S(k.cylinder(x, y, 3.2, 6, 4, P, 20), { tone: "mid" }));
  out.push(S(k.cylinder(x, y, 2, 10, MIC_Z - 10, P, 18), { tone: "mid", crease: "none" }));
  out.push(L([28, 46].map((z) => k.sideArc(x, y, 2, z, P, 12)).join(""), { tone: "faint" }));
  // shock-mount collar and the capsule body
  out.push(S(k.cylinder(x, y, 5, MIC_Z - 4, 4, P, 28), { tone: "mid" }));
  out.push(S(k.cylinder(x, y, 9, MIC_Z, MIC_TOP - MIC_Z - 14, P, 40, 0.6), { tone: "hi", crease: "lo" }));
  out.push(L(k.sideArc(x, y, 9, MIC_Z + 4, P, 30), { tone: "faint" }));
  // grille: knurled cage and a domed cap
  out.push(S(k.cylinder(x, y, 9.4, MIC_TOP - 14, 12, P, 40), { tone: "hi", crease: "lo" }));
  out.push(L(k.knurl(x, y, 9.4, MIC_TOP - 13, MIC_TOP - 3, 64, P, 0.3), { tone: "lo" }));
  out.push(L([MIC_TOP - 10, MIC_TOP - 6].map((z) => k.sideArc(x, y, 9.4, z, P, 30)).join(""), { tone: "faint" }));
  out.push(S(k.cylinder(x, y, 7.4, MIC_TOP - 2, 2.4, P, 36, 0.8), { tone: "hi", crease: "lo" }));
  out.push(L(k.ring(x, y, 4, MIC_TOP + 0.4, P, 24), { tone: "faint" }));
  // record lamp on the body, facing the viewer
  out.push(`<circle data-part="mic-led" class="of-led" cx="${at([x + 6.4, y + 6.4, MIC_Z + 10])[0].toFixed(1)}" cy="${at([x + 6.4, y + 6.4, MIC_Z + 10])[1].toFixed(1)}" r="1.5"/>`);
  return out.join("");
}

function gate() {
  const out = [`<path class="iso-halo" d="${k.haloOf(GATE, 0, 6, P)}"/>`];
  out.push(S(k.slabOf(k.insetPlan(GATE, 2), 0, 3, P, 6), { tone: "lo" }));
  out.push(S(k.slabOf(GATE, 3, GATE_H - 3, P, 6, 1), { tone: "mid" }));
  out.push(L(k.sideSeam(GATE, 12, P, 6), { tone: "faint" }));
  out.push(L(k.planOutline(k.insetPlan(GATE, 3.5), GATE_H, P, 6), { tone: "faint" }));
  out.push(L(k.planOutline({ x: FLAP.x - 1, y: FLAP.y - 0.8, w: FLAP.w + 2, d: FLAP.d + 1.6, r: 1 }, GATE_H, P, 4), { tone: "lo" }));
  out.push(D([[GATE.x + 4, GATE.y + 4], [GATE.x + GATE.w - 4, GATE.y + 4], [GATE.x + 4, GATE.y + GATE.d - 4], [GATE.x + GATE.w - 4, GATE.y + GATE.d - 4]].map(([x, y]) => at([x, y, GATE_H])), { size: 0.45 }));
  out.push(frontPlate(GATE.x + 4, GATE.x + GATE.w - 4, 15, 21, GATE.y + GATE.d, "VOICE GATE"));
  out.push(`<circle data-part="gate-led" class="of-led" cx="${at([GATE.x + GATE.w - 6, GATE.y + GATE.d, 8])[0].toFixed(1)}" cy="${at([GATE.x + GATE.w - 6, GATE.y + GATE.d, 8])[1].toFixed(1)}" r="1.3"/>`);
  out.push(L(k.ring(GATE.x + GATE.w - 6, GATE.y + GATE.d - 0.4, 0.1, 8, P, 4), { tone: "faint" }));
  return out.join("");
}

function flap() {
  return S(k.slabOf(FLAP, GATE_H - 8, 10, P, 3, 0.3), { tone: "hi", lit: true });
}

function reader() {
  const out = [`<path class="iso-halo" d="${k.haloOf(READ, 0, 6, P)}"/>`];
  out.push(S(k.slabOf(k.insetPlan(READ, 2), 0, 3, P, 8), { tone: "lo" }));
  out.push(S(k.slabOf(READ, 3, READ_H - 3, P, 8, 1.2), { tone: "mid" }));
  out.push(L(k.planOutline(k.insetPlan(READ, 4), READ_H, P, 8), { tone: "faint" }));
  out.push(D(k.corners(READ, 5).map(([x, y]) => at([x, y, READ_H])), { size: 0.45 }));
  // vent slots on the side facing right
  out.push(L(Array.from({ length: 6 }, (_, i) => k.segment([READ.x + READ.w, READ.y + 10 + i * 4, 6], [READ.x + READ.w, READ.y + 10 + i * 4, 13], P)).join(""), { tone: "faint" }));
  // drum on a bearing ring, top ticks turn while it reads
  const [x, y] = DRUM;
  out.push(S(k.cylinder(x, y, DRUM_R + 3, READ_H, 2, P, 56), { tone: "mid" }));
  out.push(S(k.cylinder(x, y, DRUM_R, READ_H + 2, DRUM_TOP - READ_H - 2, P, 64, 0.8), { tone: "hi", crease: "lo" }));
  out.push(L(k.knurl(x, y, DRUM_R, DRUM_TOP - 5, DRUM_TOP - 1, 90, P, 0.3), { tone: "lo" }));
  out.push(L([READ_H + 8, READ_H + 14].map((z) => k.sideArc(x, y, DRUM_R, z, P, 40)).join(""), { tone: "faint" }));
  out.push(L(k.ring(x, y, DRUM_R - 2.4, DRUM_TOP, P, 64), { tone: "lo" }));
  out.push(`<path data-part="drum-ticks" class="iso-line" data-tone="mid" d="${drumTicks(0)}"/>`);
  out.push(S(k.cylinder(x, y, 4.2, DRUM_TOP, 3, P, 24), { tone: "mid" }));
  out.push(D([at([x, y, DRUM_TOP + 3])], { size: 0.6, tone: "hi" }));
  // pinch roller that feeds the tape out at the front
  out.push(S(k.cylinder(-6, 18, 3.4, READ_H, 9, P, 24), { tone: "mid" }));
  out.push(S(k.cylinder(-6, 18, 1.6, READ_H + 9, 1.6, P, 16), { tone: "mid" }));
  out.push(labelPlate({ x: READ.x + 4, y: READ.y + READ.d - 13, w: 22, d: 9, r: 1 }, READ_H, [14, 10, 12]));
  out.push(frontPlate(READ.x + 8, READ.x + READ.w - 8, 7, 13, READ.y + READ.d, "INDICCONFORMER · INT8"));
  out.push(`<circle data-part="read-led" class="of-led" cx="${at([READ.x + READ.w - 4, READ.y + READ.d, 10])[0].toFixed(1)}" cy="${at([READ.x + READ.w - 4, READ.y + READ.d, 10])[1].toFixed(1)}" r="1.3"/>`);
  return out.join("");
}

const TICK_FRAMES = 24;
function drumTicks(frame) {
  const turn = (frame / TICK_FRAMES) * ((Math.PI * 2) / 40);
  return k.radialTicks(DRUM[0], DRUM[1], DRUM_R - 2.8, 40, 5, DRUM_TOP, [1.2, 2.6], P, turn).major +
    k.radialTicks(DRUM[0], DRUM[1], DRUM_R - 2.8, 40, 5, DRUM_TOP, [1.2, 2.6], P, turn).minor;
}

function translatorUnit() {
  const out = [`<path class="iso-halo" d="${k.haloOf(XLAT, 0, 6, P)}"/>`];
  out.push(S(k.slabOf(k.insetPlan(XLAT, 2), 0, 3, P, 6), { tone: "lo" }));
  out.push(S(k.slabOf(XLAT, 3, XLAT_H - 3, P, 6, 1), { tone: "mid" }));
  out.push(L(k.sideSeam(XLAT, 11, P, 6), { tone: "faint" }));
  out.push(L(k.planOutline(k.insetPlan(XLAT, 3.5), XLAT_H, P, 6), { tone: "faint" }));
  out.push(D(k.corners(XLAT, 4.5).map(([x, y]) => at([x, y, XLAT_H])), { size: 0.45 }));
  // lever quadrant: an arc slot with the two positions engraved
  const [px, py] = PIVOT;
  out.push(L(k.onTop(Array.from({ length: 17 }, (_, i) => { const a = (-150 + i * 7.5) * Math.PI / 180; return [px + Math.cos(a) * 13, py - Math.sin(a) * 13]; }), XLAT_H, P), { tone: "lo" }));
  out.push(D([at([px + Math.cos(-150 * Math.PI / 180) * 13, py + Math.sin(150 * Math.PI / 180) * 13, XLAT_H]), at([px + Math.cos(-30 * Math.PI / 180) * 13, py + Math.sin(30 * Math.PI / 180) * 13, XLAT_H])], { size: 0.55, tone: "hi" }));
  out.push(S(k.cylinder(px, py, 4.4, XLAT_H, 2.4, P, 24), { tone: "mid" }));
  out.push(frontPlate(XLAT.x + 4, XLAT.x + XLAT.w - 4, 13, 19, XLAT.y + XLAT.d, "INDICTRANS2"));
  out.push(`<circle data-part="xlat-led" class="of-led" cx="${at([XLAT.x + XLAT.w - 6, XLAT.y + XLAT.d, 7])[0].toFixed(1)}" cy="${at([XLAT.x + XLAT.w - 6, XLAT.y + XLAT.d, 7])[1].toFixed(1)}" r="1.3"/>`);
  return out.join("");
}

function laptop() {
  const out = [`<path class="iso-halo" d="${k.haloOf(LAP, 0, 4, P)}"/>`];
  out.push(S(k.slabOf(LAP, 0, LAP_H, P, 8, 0.8), { tone: "mid" }));
  const keys = { x: LAP.x + 10, y: LAP.y + 12, w: LAP.w - 20, d: 26, r: 2 };
  out.push(L(k.planOutline(keys, LAP_H, P, 4), { tone: "lo" }));
  out.push(D(k.dotGrid(keys.x + 4, keys.y + 4, 15, 4, 5.6, LAP_H, P).map((p) => p), { size: 0.5, tone: "lo" }));
  out.push(L(k.planOutline({ x: LAP.x + LAP.w / 2 - 14, y: LAP.y + 43, w: 28, d: 13, r: 2 }, LAP_H, P, 4), { tone: "lo" }));
  // hinge barrel and the lid, standing up at the back
  out.push(S(k.slabOf({ x: SCR.x0 + 6, y: SCR.y - 1, w: SCR.x1 - SCR.x0 - 12, d: 3, r: 1.4 }, LAP_H, 3, P, 4), { tone: "lo" }));
  out.push(S(k.extrude(k.ringOf({ x: SCR.x0, y: SCR.y - SCR.t, w: SCR.x1 - SCR.x0, d: SCR.t, r: 1 }, 3), SCR.z0, SCR.z1 - SCR.z0, P, { bevel: 0.6 }), { tone: "mid" }));
  const id = "of-glass";
  out.push(`<clipPath id="${id}"><path transform="${planeOf(SCR.y)}" d="${rectIn(GLASS.x0, GLASS.z0, GLASS.x1, GLASS.z1, 1.5)}"/></clipPath>`);
  out.push(`<g transform="${planeOf(SCR.y)}"><path class="of-glass" d="${rectIn(GLASS.x0, GLASS.z0, GLASS.x1, GLASS.z1, 1.5)}"/><path class="iso-line" data-tone="lo" d="${rectIn(GLASS.x0, GLASS.z0, GLASS.x1, GLASS.z1, 1.5)}"/></g>`);
  const tx = GLASS.x0 + 4;
  out.push(`<g clip-path="url(#${id})"><g transform="${planeOf(SCR.y)}">`);
  out.push(`<path class="iso-line" data-tone="faint" d="M${GLASS.x0} ${-(GLASS.z1 - 7)}H${GLASS.x1}"/>`);
  out.push(`<circle class="iso-wire-end" cx="${GLASS.x0 + 3}" cy="${-(GLASS.z1 - 3.5)}" r="0.9"/><circle class="iso-wire-end" cx="${GLASS.x0 + 6}" cy="${-(GLASS.z1 - 3.5)}" r="0.9"/>`);
  out.push(`<text class="of-scr-meta" data-part="meta" x="${tx}" y="${-(GLASS.z1 - 13)}" font-size="2.8">Notepad</text>`);
  out.push(`<text class="of-scr-heard" data-part="heard" x="${tx}" y="${-(GLASS.z0 + 22)}" font-size="3.6"></text>`);
  out.push(`<text class="of-scr-text" data-part="text" x="${tx}" y="${-(GLASS.z0 + 14)}" font-size="5.4"></text>`);
  out.push(`<rect class="of-caret" data-part="caret" x="${tx}" y="${-(GLASS.z0 + 18.6)}" width="1" height="6"/>`);
  out.push(`</g></g>`);
  out.push(D([at([SCR.x0 + (SCR.x1 - SCR.x0) / 2, SCR.y, SCR.z1 - 2.4])], { size: 0.5, tone: "lo" }));
  return out.join("");
}

// cables: microphone to gate, gate to reader. Lit pulses ride them.
const PORT_A = [GATE.x + 8, GATE.y + GATE.d, 7];
const CABLE_A = [[MIC[0] + 4, MIC[1] + MIC_BASE_R - 1, 2], [MIC[0] + 4, GATE.y + GATE.d + 8, 0.8], [PORT_A[0], GATE.y + GATE.d + 8, 0.8], [PORT_A[0], GATE.y + GATE.d + 8, PORT_A[2]], [PORT_A[0], GATE.y + GATE.d + 2.4, PORT_A[2]]];
const CABLE_B = [[GATE.x + GATE.w, GATE.y + 30, 10], [READ.x, GATE.y + 30, 10]];
const cableSvg = (pts) => k.wireSvg(at(pts[0]), at(pts[pts.length - 1]), { via: pts.slice(1, -1).map(at), tone: "lo" });

const leverEnds = (deg) => {
  const a = (deg * Math.PI) / 180;
  return [at([PIVOT[0], PIVOT[1], XLAT_H + 2.4]), at([PIVOT[0] + Math.cos(a) * 13, PIVOT[1] - Math.sin(a) * 13, XLAT_H + 12])];
};
const LEVER = { or: leverEnds(150), en: leverEnds(30) };
const tapeLine = [at([TAPE.x + 2, TAPE.y + TAPE.d / 2, 0.5]), at([TAPE.x + TAPE.w - 2, TAPE.y + TAPE.d / 2, 0.5])];

const order = [
  { depth: -1e9, svg: plate() },
  { depth: -1e8, svg: tape() },
  { depth: -1e8 + 1, svg: `<line data-part="glyphs" class="of-glyphs" x1="${tapeLine[0][0].toFixed(1)}" y1="${tapeLine[0][1].toFixed(1)}" x2="${tapeLine[1][0].toFixed(1)}" y2="${tapeLine[1][1].toFixed(1)}"/>` },
  { depth: k.depthOf([MIC[0], MIC[1], 0], P), svg: microphone() },
  { depth: k.depthOf([GATE.x + GATE.w / 2, GATE.y, 0], P), svg: gate() + `<g data-part="flap">${flap()}</g>` },
  { depth: k.depthOf([GATE.x + GATE.w / 2, GATE.y + GATE.d, 0], P) + 1, svg: S(k.slabOf({ x: PORT_A[0] - 2.4, y: PORT_A[1], w: 4.8, d: 2.4, r: 1 }, PORT_A[2] - 2.4, 4.8, P, 3), { tone: "mid" }) + cableSvg(CABLE_A) + `<path data-part="pulse-a" class="of-pulse" d=""/>` },
  { depth: k.depthOf([READ.x + READ.w / 2, READ.y, 0], P), svg: reader() },
  { depth: k.depthOf([READ.x, GATE.y + 30, 0], P) + 40, svg: cableSvg(CABLE_B) + `<path data-part="pulse-b" class="of-pulse" d=""/>` },
  { depth: k.depthOf([XLAT.x + XLAT.w / 2, XLAT.y, 0], P), svg: translatorUnit() + `<g class="iso-wire" data-tone="lit"><path data-part="lever" class="of-lever" d=""/><circle data-part="knob" class="of-knob" r="2.2"/></g>` },
  { depth: k.depthOf([LAP.x + LAP.w / 2, LAP.y, 0], P), svg: laptop() },
].sort((a, b) => a.depth - b.depth);

const svg = k.figureSvg({
  width: WIDTH,
  height: HEIGHT,
  className: "of-fig",
  label: "A desk microphone on a bench is cabled to three modules and a laptop, all on one plate with no cable leaving it. Each phrase lights the microphone, runs down the cable through a voice gate whose flap rises, into the IndicConformer reader whose drum turns and prints a tape, past the IndicTrans2 unit, and onto the laptop screen.",
  body: order.map((o) => o.svg),
});

const FIG_CSS = `
.of-led{fill:var(--anatomy-lo);transition:fill .25s}
.of-led.on{fill:var(--anatomy-lit)}
.of-pulse{fill:none;stroke:var(--anatomy-lit);stroke-width:1.6;stroke-linecap:round}
.of-glyphs{stroke:var(--anatomy-mid);stroke-width:2.2;stroke-dasharray:1.2 2.4;transition:stroke .3s}
.of-glyphs.on{stroke:var(--anatomy-lit)}
.of-lever{fill:none;stroke:var(--anatomy-mid);stroke-width:1.6;stroke-linecap:round;transition:stroke .3s}
.of-knob{fill:var(--anatomy-hi);stroke:var(--anatomy-lo);stroke-width:var(--anatomy-weight)}
.of-fig.en .of-lever{stroke:var(--anatomy-lit)}
.of-fig.en .of-knob{fill:var(--anatomy-lit)}
.of-glass{fill:var(--anatomy-shade-0)}
.of-scr-text{fill:var(--anatomy-lit);font-family:inherit}
.of-scr-heard{fill:var(--anatomy-mid);font-family:inherit}
.of-scr-meta{fill:var(--anatomy-mid);font-family:inherit}
.of-caret{fill:var(--anatomy-lit);animation:of-blink 1s steps(2) infinite}
@keyframes of-blink{50%{opacity:0}}
.of-toggle{display:inline-flex;gap:4px;padding:4px;border-radius:999px;background:var(--anatomy-face);margin-top:10px}
.of-toggle button{border:0;background:none;color:var(--anatomy-text);font:inherit;font-size:13px;height:30px;padding:0 14px;border-radius:999px;cursor:pointer}
.of-toggle button[aria-pressed="true"]{background:var(--anatomy-strong);color:var(--anatomy-page)}
@media (prefers-reduced-motion: reduce){.of-caret{animation:none}}
`;

// polyline helpers run in the page: a pulse is the stretch of a cable between s-0.12 and s
const live = `
(() => {
const fig = document.querySelector(".of-fig"), stage = fig.closest(".iso-stage"), root = stage.closest(".iso-figure");
const $ = (n) => fig.querySelector('[data-part="' + n + '"]');
const readout = root.querySelector("[data-readout]");
const still = matchMedia("(prefers-reduced-motion: reduce)");
const A = ${JSON.stringify(CABLE_A.map(at))}, B = ${JSON.stringify(CABLE_B.map(at))};
const TICKS = ${JSON.stringify(Array.from({ length: TICK_FRAMES }, (_, i) => drumTicks(i)))};
const LEVER = ${JSON.stringify(LEVER)};
const PHRASE = ${JSON.stringify(PHRASE)}, MS = ${ODIA_MS};
const FLAP_UP = ${JSON.stringify(k.axisVector(P, [0, 0, 9]))};
const lens = (pts) => pts.slice(1).map((p, i) => Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]));
const along = (pts, total, s) => { let d = s * total; const L = lens(pts); for (let i = 0; i < L.length; i++) { if (d <= L[i]) { const t = L[i] ? d / L[i] : 0; return [pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t, pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t]; } d -= L[i]; } return pts[pts.length - 1]; };
const seg = (pts, a, b) => { const total = lens(pts).reduce((x, y) => x + y, 0); if (b <= 0 || a >= 1) return ""; a = Math.max(0, a); b = Math.min(1, b); const out = [along(pts, total, a)]; let acc = 0; const L = lens(pts); for (let i = 0; i < L.length; i++) { acc += L[i]; const s = acc / total; if (s > a && s < b) out.push(pts[i + 1]); } out.push(along(pts, total, b)); return "M" + out.map((p) => p[0].toFixed(1) + " " + p[1].toFixed(1)).join("L"); };
const ease = (t) => (t <= 0 ? 0 : t >= 1 ? 1 : 1 - Math.pow(1 - t, 3));
const win = (t, a, b) => Math.max(0, Math.min(1, (t - a) / (b - a)));
let mode = "or", clock = 0, last = 0, frame = 0, visible = false, flapAt = 0, drumAt = 0, leverAt = 0, touring = !still.matches;
const CYCLE = 7.2;
const buttons = root.querySelectorAll("[data-of-mode]");
function setMode(m) { mode = m; fig.classList.toggle("en", m === "en"); buttons.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.ofMode === m))); }
function draw(t) {
  const speak = t < 1.4, pulseA = win(t, 0.3, 1.5), pulseB = win(t, 1.9, 2.5);
  $("mic-led").classList.toggle("on", speak);
  $("pulse-a").setAttribute("d", t > 0.3 && t < 1.6 ? seg(A, pulseA - 0.16, pulseA) : "");
  const gateOpen = t > 1.3 && t < 2.6;
  flapAt += ((gateOpen ? 1 : 0) - flapAt) * 0.18;
  $("flap").setAttribute("transform", "translate(" + (FLAP_UP[0] * flapAt).toFixed(2) + " " + (FLAP_UP[1] * flapAt).toFixed(2) + ")");
  $("gate-led").classList.toggle("on", gateOpen);
  $("pulse-b").setAttribute("d", t > 1.9 && t < 2.6 ? seg(B, pulseB - 0.3, pulseB) : "");
  const reading = t > 2.3 && t < 4.2;
  if (reading) drumAt = (drumAt + 0.6) % ${TICK_FRAMES};
  $("drum-ticks").setAttribute("d", TICKS[Math.floor(drumAt)]);
  $("read-led").classList.toggle("on", reading);
  const glyphs = $("glyphs");
  glyphs.classList.toggle("on", t > 2.6 && t < 5.4);
  if (t > 2.6 && t < 5.4) glyphs.style.strokeDashoffset = String(-(t - 2.6) * 18);
  leverAt += ((mode === "en" ? 1 : 0) - leverAt) * 0.12;
  const [p, a] = LEVER.or, [, b] = LEVER.en, tip = [a[0] + (b[0] - a[0]) * ease(leverAt), a[1] + (b[1] - a[1]) * ease(leverAt)];
  $("lever").setAttribute("d", "M" + p[0].toFixed(1) + " " + p[1].toFixed(1) + "L" + tip[0].toFixed(1) + " " + tip[1].toFixed(1));
  $("knob").setAttribute("cx", tip[0].toFixed(1)); $("knob").setAttribute("cy", tip[1].toFixed(1));
  $("xlat-led").classList.toggle("on", mode === "en" && t > 3.6 && t < 5.4);
  const typeFrom = mode === "en" ? 4.0 : 3.6, out = PHRASE[mode];
  const chars = Math.max(0, Math.min(out.length, Math.floor((t - typeFrom) * 18)));
  const shown = [...out].slice(0, Math.round(chars * [...out].length / out.length)).join("");
  const text = $("text");
  if (text.textContent !== shown) text.textContent = shown;
  $("heard").textContent = mode === "en" && t > 4.0 ? PHRASE.or : "";
  const caret = $("caret");
  let w = 0; try { w = shown ? text.getComputedTextLength() : 0; } catch (e) {}
  caret.setAttribute("x", (+text.getAttribute("x") + w + 0.6).toFixed(1));
  const line = (mode === "en" ? "Odia \\u2192 English" : "Odia") + " \\u00b7 " + (t < 1.4 ? "listening" : t < 2.6 ? "voice detected" : t < typeFrom ? "reading Odia" : chars < out.length ? "writing" : "pasted in " + MS + " ms") + " \\u00b7 offline";
  if (readout.textContent !== line) readout.textContent = line;
}
function tick(now) {
  const dt = last ? Math.min((now - last) / 1000, 1 / 20) : 1 / 60; last = now;
  clock += dt;
  if (clock > CYCLE) { clock = 0; if (touring) setMode(mode === "or" ? "en" : "or"); }
  draw(clock);
  frame = visible ? requestAnimationFrame(tick) : 0;
}
const run = () => { if (!frame && visible && !still.matches) { last = 0; frame = requestAnimationFrame(tick); } };
new IntersectionObserver((e) => { visible = e[e.length - 1].isIntersecting; if (visible) run(); }, { rootMargin: "80px 0px" }).observe(stage);
const pick = (m) => { touring = false; setMode(m); clock = 0; if (still.matches) { leverAt = m === "en" ? 1 : 0; draw(6); } run(); };
buttons.forEach((b) => b.addEventListener("click", () => pick(b.dataset.ofMode)));
stage.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(mode === "or" ? "en" : "or"); } });
stage.addEventListener("click", () => pick(mode === "or" ? "en" : "or"));
setMode("or");
draw(still.matches ? 6 : 0);
})();
`;

const toggle = `<div class="of-toggle" role="group" aria-label="Write as"><button type="button" data-of-mode="or" aria-pressed="true">Odia</button><button type="button" data-of-mode="en" aria-pressed="false">Odia → English</button></div>`;
const figure = k.plateHtml({
  fig: "Fig 1",
  title: "How OpenFlow hears Odia",
  hint: "Click to switch Odia / English",
  readout: "Odia · listening · offline",
  keys: [
    { mark: "lit", label: "What moves: the phrase, the gate flap, the tape and the translator lever" },
    { mark: "raised", label: "Microphone, three modules and a laptop on one plate: no cable leaves it" },
  ],
  caption: `A phrase lights the microphone and runs down its cable. The voice gate lifts its flap only while there is speech, the IndicConformer drum turns and prints Odia onto the tape, and with Odia → English selected the IndicTrans2 lever swings across and translates on the way. The laptop types the result. Measured on ${R.clips} FLEURS clips, a phrase takes about ${ODIA_MS} ms on a laptop CPU.`,
  body: `<div class="iso-stage" tabindex="0" role="button" aria-label="Switch between Odia and Odia to English">${svg}</div>${toggle}`,
});

const fragment = `<div class="iso of-wrap" data-theme="${theme}"><style>${k.ISO_CSS}${FIG_CSS}</style>${figure}<script>${live}</script></div>`;
const page = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>How OpenFlow hears Odia</title><style>body{margin:0;background:${theme === "light" ? "#f2f2ef" : "#000"};font:14px/1.6 'General Sans',system-ui,sans-serif}.of-page{width:min(820px,100% - 32px);margin:48px auto}</style></head><body><main class="of-page">${fragment}</main></body></html>`;
writeFileSync(join(HERE, theme === "light" ? "odia-desk-light.html" : "odia-desk.html"), page);

if (theme === "dark") {
  const index = join(HERE, "..", "..", "index.html");
  const raw = readFileSync(index, "utf-8");
  const re = /<!-- fig:odia-desk -->[\s\S]*?<!-- \/fig:odia-desk -->/;
  if (re.test(raw)) {
    writeFileSync(index, raw.replace(re, () => `<!-- fig:odia-desk -->${fragment}<!-- /fig:odia-desk -->`));
    console.log("updated docs/index.html");
  }
}
console.log("wrote", theme === "light" ? "odia-desk-light.html" : "odia-desk.html");
