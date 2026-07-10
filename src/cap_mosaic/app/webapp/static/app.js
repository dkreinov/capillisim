"use strict";
const $ = (id) => document.getElementById(id);
const PITCH = 32; // mm
const ARCMIN = 3437.75;

let imageId = null;
let versions = [];  // [{id, label, aspect}] — Original, crops, AI edits; imageId = active
let aspect = 1;
let selFrac = null;  // {x0,y0,x1,y1} in image fractions
let highlight = null;  // BOM colour being isolated (hex), or null
let bgColors = [];     // colours the user sent to the background (hex strings)
let bgSeeds = [];      // region exclusions: {fx, fy, hex} cell-centre seeds
let curSimSrc = null, curTargetSrc = null;  // for hold-to-compare

function mode() {
  return document.querySelector('input[name=mode]:checked').value;
}
function sizeMm() { return Number($("size").value); }
function distM() { return Number($("dist").value); }
function preset() { return $("preset").value; }
function thicken() { return $("thicken").checked; }
function dither() { return $("dither").checked; }
function bgColor() { return $("bgColor").value; }
function realOnly() { return $("realOnly").checked; }
function useInv() { return $("useInv").checked; }
function fromMyCaps() {
  return document.querySelector('input[name=planFrom]:checked').value === "mine";
}
function colorsN() { return Math.max(4, Math.min(24, Number($("colorsN").value) || 12)); }
function ownThreshold() { return Math.max(2, Math.min(30, Number($("ownThr").value) || 12)); }
function unlimitedStock() { return $("unlimitedStock").checked; }
function shape() { return $("shape").value; }
function extraParams() {
  const p = { bg_color: bgColor(), dither: dither(), colors: colorsN() };
  if (preset()) p.preset = preset();
  if (thicken()) p.thicken = true;
  if (realOnly()) p.real_only = true;
  if (useInv()) p.inventory = true;
  if (fromMyCaps()) {
    p.from_my_caps = true;
    p.own_threshold = ownThreshold();
    if (unlimitedStock()) p.unlimited_stock = true;
  }
  if (bgColors.length) p.bg_colors = bgColors.map((h) => h.slice(1)).join(",");
  if (bgSeeds.length) {
    p.bg_seeds = bgSeeds.map((s) => `${s.fx}:${s.fy}:${s.hex.slice(1)}`).join(",");
  }
  if (shape() === "poly") {
    if (polyFrac) {
      p.poly = polyFrac.map((q) => `${q.x.toFixed(4)},${q.y.toFixed(4)}`).join(";");
    }
    // freeform selected but not drawn yet -> plan stays rectangular
  } else if (shape() !== "rect") {
    p.shape = shape();
  }
  return p;
}

// transient inline notification — replaces blocking alert() popups
let toastTimer = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 3500);
}

// disable the AI buttons while one of them is talking to the API (they cost money)
const AI_BTNS = ["askLLM", "aiSimplify", "applyAI"];
function aiBusy(on, activeId, workingText) {
  for (const id of AI_BTNS) {
    const b = $(id);
    b.disabled = on;
    if (id === activeId) {
      if (on) { b.dataset.label = b.textContent; b.textContent = workingText; }
      else if (b.dataset.label) { b.textContent = b.dataset.label; }
    }
  }
}

function readQuality(d) {
  const arc = (PITCH / 1000) / d * ARCMIN;
  if (arc > 25) return "you see caps";
  if (arc > 3) return "reads as picture";
  return "smooth";
}

// --- wheel zoom: scrolling over the preview IS walking closer/farther ---
const FOV_DEG = 50;                    // matches view_at_distance's frame
function apparentFrac(widthM, d) {     // client mirror of core/sizing.apparent_fraction
  if (d <= 0) return 1;
  return Math.min(1, (2 * Math.atan(widthM / 2 / d) * 180 / Math.PI) / FOV_DEG);
}
// distance behind the CURRENTLY shown pixels vs the render on its way; the gap
// between them is bridged by an instant CSS scale until the real render lands
let simBaseDist = null, inflightDist = null;

function previewZoom() {
  const el = $("sim");
  if (simBaseDist == null) { el.style.transform = ""; return; }
  const w = sizeMm() / 1000;
  const base = apparentFrac(w, simBaseDist);
  let s = base > 0 ? apparentFrac(w, distM()) / base : 1;
  s = Math.max(0.2, Math.min(5, s));   // cosmetic clamp on upscale blur
  el.style.transform = Math.abs(s - 1) < 1e-3 ? "" : `scale(${s})`;
}

function updateSimHintClient() {
  if (fromMyCaps() && !unlimitedStock()) return;  // fitted piece: server hint stands
  const w = sizeMm() / 1000, d = distM();
  const pct = Math.round(100 * apparentFrac(w, d));
  $("simhint").textContent =
    `${w.toFixed(2)} m wide, seen from ${d.toFixed(1)} m — fills ~${pct}% of your view · ${readQuality(d)}`;
}

// shared by the slider and the wheel: readouts update instantly, render debounced
function applyDistanceUI() {
  $("distVal").textContent = distM().toFixed(1) + " m";
  $("quality").textContent = readQuality(distM());
  updateSimHintClient();
  previewZoom();
  debounced();
}

function setDistance(d) {
  const el = $("dist");
  d = Math.round(Math.max(+el.min, Math.min(+el.max, d)) * 10) / 10;
  if (d === distM()) return;
  el.value = d;
  applyDistanceUI();
}

// --- upload ---
const dz = $("dropzone");
dz.addEventListener("click", () => $("fileInput").click());
$("fileInput").addEventListener("change", (e) => { if (e.target.files[0]) upload(e.target.files[0]); });
["dragover", "dragenter"].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("hot"); }));
["dragleave", "drop"].forEach((ev) =>
  dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("hot"); }));
dz.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) upload(e.dataTransfer.files[0]); });

// paste an image from the clipboard (Ctrl/Cmd+V) anywhere on the page
document.addEventListener("paste", (e) => {
  const items = (e.clipboardData || window.clipboardData)?.items || [];
  for (const it of items) {
    if (it.type && it.type.startsWith("image/")) {
      const blob = it.getAsFile();
      if (blob) { e.preventDefault(); upload(blob); }
      return;
    }
  }
});

async function upload(file) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/upload", { method: "POST", body: fd });
  if (!r.ok) { toast("Upload failed — is that a valid image file?"); return; }
  const b = await r.json();
  dz.querySelector("p").innerHTML = `loaded ${b.width}×${b.height} <small>· drop / paste another to replace</small>`;
  dz.classList.add("slim");
  versions = [];  // a fresh upload starts a fresh version history
  activePattern = null;
  addVersion(b, "Original");
  $("imagepanel").hidden = false;
  $("origwrap").hidden = false;
  $("croptools").hidden = false;
  $("versionswrap").hidden = false;
  $("imageWhere").hidden = false;
  $("controls").hidden = false;
  $("stats").hidden = false;
  $("bomwrap").hidden = false;
  document.getElementById("menu-image").open = false;  // no floating panel over the stage
}

function setPreview(id) { $("orig").src = "/image?image_id=" + id + "&_=" + Date.now(); }

// --- image versions: Original, crops, AI edits — switch and save any of them ---
function addVersion(b, kind) {
  const n = versions.filter((v) => v.label.startsWith(kind)).length;
  const label = n === 0 ? kind : `${kind} ${n + 1}`;
  versions.push({ id: b.id, label, aspect: b.aspect });
  renderVersions();
  activateVersion(b.id);
}

function activateVersion(id) {
  const v = versions.find((x) => x.id === id);
  if (!v) return;
  imageId = v.id; aspect = v.aspect;
  highlight = null;              // isolate/selection state belongs to the old plan
  bgColors = []; bgSeeds = [];   // ...as do the background exclusions
  renderBgChips();
  clearPoly();                   // outline fractions refer to the old frame
  setPreview(v.id); clearSelection();
  renderVersions();
  refresh(); loadCritique();     // loadCritique also clears the stale AI verdict
}

function renderVersions() {
  const box = $("versions"); box.innerHTML = "";
  for (const v of versions) {
    const tile = document.createElement("div");
    tile.className = "vtile" + (v.id === imageId ? " active" : "");
    tile.innerHTML =
      `<img src="/image?image_id=${v.id}" alt="${v.label}" loading="lazy" />` +
      `<span class="vlabel">${v.label}</span>` +
      `<a class="vsave" href="/image?image_id=${v.id}" download="${v.label.toLowerCase().replace(/ /g, "-")}.png" title="save this version">⬇</a>`;
    tile.addEventListener("click", (e) => {
      if (e.target.closest(".vsave")) return;  // the save link downloads, not switches
      activateVersion(v.id);
    });
    box.appendChild(tile);
  }
}

let lastRec = null;
let lastAIActions = [];

// the AI-verdict box: text + the apply button that appears when the judge
// recommended concrete settings
function showAI(text, actions) {
  $("critique").open = true;   // the verdict lives in the collapsible body — reveal it
  $("cllm").hidden = false;
  $("cllmText").textContent = text;
  lastAIActions = actions || [];
  $("applyAI").hidden = lastAIActions.length === 0;
}

// the instant heuristic check's own apply, offered inline with its tips
function applyHeuristic() {
  if (!lastRec) return;
  $("dither").checked = !!lastRec.dither;
  $("thicken").checked = !!lastRec.thicken;
  $("preset").value = lastRec.preset || "";
  const w = Math.round((lastRec.min_size_m || 1) * 1000);
  $("size").value = w; $("sizeVal").textContent = (w / 1000).toFixed(2) + " m";
  refresh();
}

async function loadCritique() {
  if (!imageId) return;
  const r = await fetch("/critique?" + new URLSearchParams({ image_id: imageId, mode: mode() }));
  if (!r.ok) return;
  const c = await r.json();
  lastRec = c.recommend;
  $("cllm").hidden = true;       // stale AI verdict belongs to the previous image
  $("applyAI").hidden = true;
  $("beforewrap").hidden = true;  // ...as does the before-snapshot
  const box = $("critique"); box.hidden = false;
  const s = $("cscore"); s.textContent = c.score;
  s.className = "cscore " + c.verdict;
  $("cverdict").textContent = `Cap-art check: ${c.verdict} (${c.score}/100)`;
  $("csig").textContent = `contrast ${c.signals.contrast} · detail ${c.signals.detail_floor} caps · bg ${c.signals.bg_spread}`;
  const ul = $("ctips"); ul.innerHTML = "";
  for (const t of c.tips) { const li = document.createElement("li"); li.textContent = t; ul.appendChild(li); }
  const li = document.createElement("li");
  li.className = "applylink";
  li.innerHTML = `<a data-tip="Apply this check's suggestions: minimum readable size + recommended toggles. Free, no AI call.">✨ apply these suggestions</a>`;
  li.addEventListener("click", applyHeuristic);
  ul.appendChild(li);
}

$("askLLM").addEventListener("click", async () => {
  if (!imageId) return;
  showAI("asking the AI judge…");
  aiBusy(true, "askLLM", "🧠 judging…");
  try {
    const r = await fetch("/critique?" + new URLSearchParams({ image_id: imageId, mode: mode(), llm: true }));
    if (!r.ok) { showAI("AI judge failed"); return; }
    const c = await r.json();
    const l = c.llm || {};
    if (l.error) { showAI("AI judge: " + l.error); return; }
    const tips = (l.tips || []).map((t) => `• ${t}`).join("\n");
    const alt = l.better_subject ? `\nTry instead: ${l.better_subject}` : "";
    showAI(`🧠 ${l.verdict} (${l.score}/100) — ${l.model}\n${tips}${alt}`, l.actions);
  } finally { aiBusy(false, "askLLM"); }
});

$("applyAI").addEventListener("click", () => {
  if (!lastAIActions.length) return;
  // snapshot the current sim as "before", then apply the judge's settings
  if (curSimSrc) { $("beforeimg").src = curSimSrc; $("beforewrap").hidden = false; }
  lastAIActions.forEach(applyAction);
  const applied = lastAIActions.map((a) => `${a.set} → ${a.value}`).join(" · ");
  $("cllmText").textContent += `\n🪄 applied: ${applied}`;
  refresh();
});

// apply a whitelisted judge action to its control (getElementById — the helper
// names `dither`/`preset` are functions and would shadow the elements)
function applyAction(a) {
  const el = document.getElementById.bind(document);
  if (a.set === "colors") el("colorsN").value = a.value;
  else if (a.set === "thicken") el("thicken").checked = !!a.value;
  else if (a.set === "dither") el("dither").checked = !!a.value;
  else if (a.set === "preset") el("preset").value = a.value;
  else if (a.set === "size_m") {
    const w = Math.round(a.value * 1000);
    el("size").value = w; el("sizeVal").textContent = (w / 1000).toFixed(2) + " m";
  }
}

$("beforeClose").addEventListener("click", () => { $("beforewrap").hidden = true; });

$("aiSimplify").addEventListener("click", async () => {
  if (!imageId) return;
  showAI("AI is simplifying the image… (can take ~20s)");
  aiBusy(true, "aiSimplify", "🎨 painting…");
  try {
    const r = await fetch("/simplify?" + new URLSearchParams({ image_id: imageId }));
    if (!r.ok) { showAI("AI simplify failed (" + r.status + ")"); toast("AI simplify failed"); return; }
    // becomes a new version; every earlier version stays one click away in the strip
    addVersion(await r.json(), "AI simplified");
  } finally { aiBusy(false, "aiSimplify"); }
});

// --- controls ---
$("size").addEventListener("input", () => { $("sizeVal").textContent = (sizeMm() / 1000).toFixed(2) + " m"; debounced(); });
$("dist").addEventListener("input", applyDistanceUI);
document.querySelectorAll('input[name=mode]').forEach((r) => r.addEventListener("change", refresh));
$("preset").addEventListener("change", refresh);
$("thicken").addEventListener("change", refresh);
$("realOnly").addEventListener("change", refresh);
$("dither").addEventListener("change", refresh);
$("useInv").addEventListener("change", refresh);
$("colorsN").addEventListener("change", refresh);
$("ownThr").addEventListener("input", () => { $("ownThrVal").textContent = ownThreshold(); debounced(); });
$("unlimitedStock").addEventListener("change", () => { syncCapsMode(); refresh(); });
// buttons/links that live inside a collapsible <summary> must not toggle it
["askLLM", "aiSimplify", "capmap"].forEach((id) => {
  const el = $(id);
  if (el) el.addEventListener("click", (e) => e.stopPropagation());
});

// caps-I-own mode implies photo rendering (the plan IS your caps); the preview
// checkbox locks on there and restores the user's choice back in ideal mode
let realOnlyBeforeLock = null;
function syncCapsMode() {
  const mine = fromMyCaps();
  const ro = $("realOnly");
  $("ownOptsRow").hidden = !mine;   // caps-I-own options only apply in that mode
  // the match-tolerance slider is meaningless when we assume unlimited stock
  $("ownThrLabel").style.display = mine && !unlimitedStock() ? "" : "none";
  if (mine) {
    if (realOnlyBeforeLock === null) realOnlyBeforeLock = ro.checked;
    ro.checked = true; ro.disabled = true;
    $("realOnlyNote").hidden = false;
  } else {
    ro.disabled = false;
    if (realOnlyBeforeLock !== null) { ro.checked = realOnlyBeforeLock; realOnlyBeforeLock = null; }
    $("realOnlyNote").hidden = true;
  }
}
document.querySelectorAll('input[name=planFrom]').forEach((r) =>
  r.addEventListener("change", () => { syncCapsMode(); refresh(); }));

// --- patterns from the owned inventory: a gallery driven by the server's
//     registry; each pattern lands as a version, and regenerating (new kind,
//     new rectangle size) REPLACES the active pattern version in the strip ---
let activePattern = null;   // {kind} while a pattern version is active
function patUnlimited() { return $("patUnlimited").checked; }

async function generatePattern(kind) {
  const q = new URLSearchParams({ kind, width_mm: Math.round(patRect.w),
                                  height_mm: Math.round(patRect.h) });
  if (patUnlimited()) q.set("unlimited", true);
  if (shape() === "poly" && polyFrac) {
    q.set("poly", polyFrac.map((p) => `${p.x.toFixed(4)},${p.y.toFixed(4)}`).join(";"));
  } else if (shape() !== "rect") {
    q.set("shape", shape());
  }
  const r = await fetch("/pattern?" + q.toString());
  if (!r.ok) {
    toast(r.status === 404
      ? "Scan some caps first — or tick 'unlimited stock' to preview with a reference palette."
      : "Pattern failed");
    return;
  }
  const b = await r.json();
  if (!versions.length) {  // patterns can be the very first "image"
    $("imagepanel").hidden = false; $("origwrap").hidden = false; $("croptools").hidden = false;
    $("versionswrap").hidden = false; $("controls").hidden = false;
    $("stats").hidden = false; $("bomwrap").hidden = false;
  }
  const prev = activePattern &&
    versions.find((v) => v.label.startsWith("Pattern") && v.id === imageId);
  if (prev) {           // regenerate in place: no version-strip spam
    prev.id = b.id; prev.aspect = b.aspect; prev.label = `Pattern ${kind}`;
    activePattern = { kind };
    renderVersions();
    activateVersion(b.id);
  } else {
    addVersion(b, `Pattern ${kind}`);
    activePattern = { kind };
  }
  toast(b.missing > 0
    ? `Pattern needs ${b.cells.toLocaleString()} caps — you're ${b.missing.toLocaleString()} short (bare cells shown).`
    : `Pattern laid out from ${b.caps.toLocaleString()} caps.`);
  drawPatRect();
}

(async function loadPatternGallery() {
  try {
    const b = await (await fetch("/pattern_kinds")).json();
    const box = $("patGallery");
    for (const kind of b.kinds) {
      const tile = document.createElement("button");
      tile.className = "pat";
      tile.dataset.tip = (b.blurbs && b.blurbs[kind]) || kind;
      tile.innerHTML =
        `<img src="/pattern_thumb?kind=${kind}" alt="${kind}" loading="lazy" /><span>${kind}</span>`;
      tile.addEventListener("click", async () => {
        tile.disabled = true;
        try { await generatePattern(kind); } finally { tile.disabled = false; }
      });
      box.appendChild(tile);
    }
  } catch (_) { /* gallery unavailable; the rest of the app still works */ }
})();

$("patUnlimited").addEventListener("change", () => {
  drawPatRect();
  if (activePattern) generatePattern(activePattern.kind);
});

// --- the pattern sizing rectangle: a physical-mm input widget on the stage.
//     Visible in Pattern mode; SE handle resizes, body drag just repositions
//     the widget. Red border + label = your stock can't fill it. ---
const patLayer = window.CapOverlay.attach(document.querySelector(".simwrap"));
const STAGE_SPAN_MM = 4000;              // the stage width represents 4 m
let patRect = { w: 1000, h: 750 };       // the piece being sized, in mm
let patPos = { x: 0.5, y: 0.5 };         // widget centre, stage fractions
let patDrag = null;                       // {kind:"resize"|"move", ...}
let patTimer = null;

function stagePx() { return document.querySelector(".simwrap").getBoundingClientRect(); }
function mmPerPx() { return STAGE_SPAN_MM / Math.max(1, stagePx().width); }

// exact JS mirror of core.geometry.grid_for_frame's cell count
function cellsForFrame(wMm, hMm, d = 32) {
  const rp = d * Math.sqrt(3) / 2;
  if (hMm < d) return 0;
  let n = 0;
  const rows = Math.floor((hMm - d) / rp) + 1;
  for (let r = 0; r < rows; r++) {
    const usable = wMm - d - (r % 2 ? d / 2 : 0);
    n += usable >= 0 ? Math.floor(usable / d) + 1 : 0;
  }
  return n;
}

function areaFraction() {
  const s = shape();
  if (s === "poly" && polyFrac) {       // shoelace on the drawn outline
    let a = 0, j = polyFrac.length - 1;
    for (let i = 0; i < polyFrac.length; i++) {
      a += (polyFrac[j].x + polyFrac[i].x) * (polyFrac[j].y - polyFrac[i].y);
      j = i;
    }
    return Math.abs(a) / 2;
  }
  return { rect: 1, circle: Math.PI / 4, ellipse: Math.PI / 4,
           diamond: 0.5, hex: 0.75, heart: 0.55 }[s] ?? 1;
}

function patEstimate() {
  return Math.round(cellsForFrame(patRect.w, patRect.h) * areaFraction());
}

function drawPatRect() {
  patLayer.clear();
  if (mode() !== "pattern") return;
  patLayer.sync();
  const host = stagePx();
  const scale = 1 / mmPerPx();
  const w = patRect.w * scale, h = patRect.h * scale;
  const x = patPos.x * host.width - w / 2, y = patPos.y * host.height - h / 2;
  const est = patEstimate();
  const missing = patUnlimited() ? 0 : Math.max(0, est - ownedTotal);
  const cls = missing > 0 ? " short" : "";
  const box = patLayer.el("rect", { x, y, width: Math.max(8, w), height: Math.max(8, h),
                                    class: "patrect" + cls, rx: 6 });
  box.style.pointerEvents = "all";
  box.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    patDrag = { kind: "move", x0: e.clientX, y0: e.clientY, pos0: { ...patPos } };
  });
  const hd = patLayer.el("circle", { cx: x + w, cy: y + h, r: 8, class: "pathandle" + cls });
  hd.style.pointerEvents = "all";
  hd.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    patDrag = { kind: "resize", left: x, top: y };
  });
  const label = patLayer.el("text", { x: x + 10, y: Math.max(16, y - 10),
                                      class: "patlabel" + cls });
  label.textContent =
    `${(patRect.w / 1000).toFixed(2)} × ${(patRect.h / 1000).toFixed(2)} m · ~${est.toLocaleString()} caps`
    + (missing > 0 ? ` · ${missing.toLocaleString()} caps missing` : "");
}

window.addEventListener("pointermove", (e) => {
  if (!patDrag) return;
  const host = stagePx();
  if (patDrag.kind === "resize") {
    patRect.w = Math.max(200, (e.clientX - host.left - patDrag.left) * mmPerPx());
    patRect.h = Math.max(200, (e.clientY - host.top - patDrag.top) * mmPerPx());
  } else {
    patPos.x = Math.min(0.95, Math.max(0.05,
      patDrag.pos0.x + (e.clientX - patDrag.x0) / host.width));
    patPos.y = Math.min(0.95, Math.max(0.05,
      patDrag.pos0.y + (e.clientY - patDrag.y0) / host.height));
  }
  drawPatRect();
});
window.addEventListener("pointerup", () => {
  if (!patDrag) return;
  const resized = patDrag.kind === "resize";
  patDrag = null;
  if (resized && activePattern) {       // regenerate the pattern at the new size
    clearTimeout(patTimer);
    patTimer = setTimeout(() => generatePattern(activePattern.kind), 350);
  }
});
document.querySelectorAll('input[name=mode]').forEach((r) =>
  r.addEventListener("change", drawPatRect));
new ResizeObserver(drawPatRect).observe(document.querySelector(".simwrap"));

$("scanBtn").addEventListener("click", async () => {
  const r = await fetch("/scanner/launch", { method: "POST" });
  if (!r.ok) { toast("Could not start the scanner"); return; }
  toast("Scanner opening in its own window on this computer — place a cap on the card; Q there to finish.");
});

$("copyPrompt").addEventListener("click", async () => {
  const r = await fetch("/palette_prompt");
  if (!r.ok) { toast("Scan some caps first — the inventory is empty."); return; }
  const b = await r.json();
  try { await navigator.clipboard.writeText(b.prompt); toast(`AI prompt copied (${b.colors} colours, ${b.caps} caps) — paste it into any image generator.`); }
  catch (_) { toast("Clipboard blocked — prompt logged to console."); console.log(b.prompt); }
});

// dim the sim while a new render is on its way; the load event clears it
["load", "error"].forEach((ev) =>
  $("sim").addEventListener(ev, () => document.querySelector(".simwrap").classList.remove("loading")));
// the landed render is authoritative for its distance: drop the interim scale
$("sim").addEventListener("load", () => { simBaseDist = inflightDist; $("sim").style.transform = ""; });
$("sim").addEventListener("error", () => { $("sim").style.transform = ""; });

// scroll over the preview = change viewing distance (ctrl+wheel = trackpad pinch)
document.querySelector(".simwrap").addEventListener("wheel", (e) => {
  if (!imageId) return;
  // the fitted caps-I-own piece is shown sharp at its real size — the server
  // ignores distance there, so let the page scroll normally
  if (fromMyCaps() && !unlimitedStock()) return;
  e.preventDefault();
  const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;   // line-scroll mice -> px
  setDistance(distM() * Math.exp((e.ctrlKey ? 0.003 : 0.0015) * dy));
}, { passive: false });

// --- click a colour on the preview to send it to the background (bare board);
//     Shift+click removes only the connected region. Click again to restore. ---
function renderBgChips() {
  const bar = $("bgbar"), box = $("bgchips");
  box.innerHTML = "";
  const chip = (label, hex, onRemove) => {
    const s = document.createElement("span");
    s.className = "bgchip";
    s.innerHTML = `<span class="sw" style="background:${hex}"></span>${label} <b>×</b>`;
    s.addEventListener("click", () => { onRemove(); renderBgChips(); refresh(); });
    box.appendChild(s);
  };
  for (const hex of bgColors) {
    chip(hex, hex, () => { bgColors = bgColors.filter((h) => h !== hex); });
  }
  bgSeeds.forEach((seed, i) => {
    chip(`region ${seed.hex}`, seed.hex, () => { bgSeeds.splice(i, 1); });
  });
  bar.hidden = bgColors.length === 0 && bgSeeds.length === 0;
}

$("bgClear").addEventListener("click", () => {
  bgColors = []; bgSeeds = [];
  renderBgChips(); refresh();
});

$("sim").addEventListener("click", async (e) => {
  if (!imageId) return;
  // while a zoom scale or a fresh render is pending, the pixels on screen
  // don't match the current params — a pick there would land on the wrong cell
  if ($("sim").style.transform) return;
  if (document.querySelector(".simwrap").classList.contains("loading")) return;
  const r = $("sim").getBoundingClientRect();
  const q = new URLSearchParams({
    image_id: imageId, mode: mode(), pitch_mm: PITCH,
    size_mm: sizeMm(), distance_m: distM(),
    fx: ((e.clientX - r.left) / r.width).toFixed(4),
    fy: ((e.clientY - r.top) / r.height).toFixed(4),
    ...extraParams(),
  });
  const res = await fetch("/pick?" + q.toString());
  if (!res.ok) return;
  const b = await res.json();
  if (!b.hit) return;
  if (b.excluded_by === "color") {
    bgColors = bgColors.filter((h) => h !== b.hex);          // click again = restore
  } else if (b.excluded_by === "seed") {
    bgSeeds.splice(b.seed_index, 1);                          // restore that region
  } else if (b.bare) {
    toast("That cell is already bare board."); return;
  } else if (e.shiftKey) {
    if (bgSeeds.length >= 64) { toast("Too many regions — clear some first."); return; }
    bgSeeds.push({ fx: b.fx, fy: b.fy, hex: b.hex });
  } else {
    bgColors.push(b.hex);
  }
  renderBgChips(); refresh();
});

// hold the compare button to swap the cap sim for the original (same framing)
const _cmp = $("compareBtn");
const _showTarget = () => { if (curTargetSrc) $("sim").src = curTargetSrc; };
const _showSim = () => { if (curSimSrc) $("sim").src = curSimSrc; };
_cmp.addEventListener("mousedown", _showTarget);
["mouseup", "mouseleave"].forEach((e) => _cmp.addEventListener(e, _showSim));
_cmp.addEventListener("touchstart", (e) => { e.preventDefault(); _showTarget(); });
_cmp.addEventListener("touchend", _showSim);
$("bgColor").addEventListener("input", debounced);

// --- region crop: drag a rectangle on the original image ---
const origImg = $("orig");
const selBox = $("sel");
let drag = null;

function clearSelection() {
  selFrac = null; drag = null;
  selBox.hidden = true;
  $("cropBtn").disabled = true;
}

function imgRect() { return origImg.getBoundingClientRect(); }

origImg.addEventListener("mousedown", (e) => {
  if (polyDrawing()) return;   // outline clicks must not start a crop drag
  e.preventDefault();
  const r = imgRect();
  drag = { x: e.clientX - r.left, y: e.clientY - r.top };
});
window.addEventListener("mousemove", (e) => {
  if (!drag) return;
  const r = imgRect();
  const cx = Math.max(0, Math.min(r.width, e.clientX - r.left));
  const cy = Math.max(0, Math.min(r.height, e.clientY - r.top));
  const x = Math.min(drag.x, cx), y = Math.min(drag.y, cy);
  const w = Math.abs(cx - drag.x), h = Math.abs(cy - drag.y);
  Object.assign(selBox.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
  selBox.hidden = false;
  selFrac = { x0: x / r.width, y0: y / r.height, x1: (x + w) / r.width, y1: (y + h) / r.height };
});
window.addEventListener("mouseup", () => {
  if (!drag) return;
  drag = null;
  const ok = selFrac && (selFrac.x1 - selFrac.x0) > 0.02 && (selFrac.y1 - selFrac.y0) > 0.02;
  $("cropBtn").disabled = !ok;
  if (!ok) clearSelection();
});

$("cropBtn").addEventListener("click", async () => {
  if (!selFrac || !imageId) return;
  const q = new URLSearchParams({ image_id: imageId, ...selFrac });
  const r = await fetch("/crop?" + q.toString());
  if (!r.ok) { toast("Crop failed — try a larger selection."); return; }
  addVersion(await r.json(), "Crop");
});

// --- freeform shape: click points on the original image to draw the outline ---
let polyFrac = null;      // the committed outline, [{x, y}] image fractions
let polyDraft = null;     // vertices while drawing (null = not drawing)
const polyLayer = window.CapOverlay.attach($("origwrap"), $("orig"));

function polyDrawing() { return polyDraft !== null; }

function redrawPoly() {
  polyLayer.clear();
  const pts = polyDraft || polyFrac;
  if (!pts || !pts.length) return;
  polyLayer.sync();
  const r = polyLayer.rect();
  const px = pts.map((q) => `${q.x * r.width},${q.y * r.height}`).join(" ");
  polyLayer.el(polyDraft ? "polyline" : "polygon", {
    points: px, fill: "rgba(240,200,80,.14)", stroke: "#f0c850",
    "stroke-width": "2", "stroke-dasharray": polyDraft ? "5 4" : "0",
  });
  for (const q of pts) {
    polyLayer.el("circle", { cx: q.x * r.width, cy: q.y * r.height, r: "4",
                             fill: "#f0c850", stroke: "#1c2230" });
  }
}

function startPolyDraw() {
  polyDraft = [];
  $("drawPoly").classList.add("active");
  origImg.style.cursor = "crosshair";
  toast("Click points on your image — double-click or Enter closes the outline (min 3), Esc cancels, Backspace undoes a point.");
  redrawPoly();
}

function finishPolyDraw(commit) {
  if (commit) {
    // double-click also fires two click events: drop near-duplicate vertices
    const pts = polyDraft.filter((q, i, a) =>
      i === 0 || Math.hypot(q.x - a[i - 1].x, q.y - a[i - 1].y) > 0.005);
    if (pts.length < 3) { toast("An outline needs at least 3 points."); return; }
    polyFrac = pts;
  }
  polyDraft = null;
  $("drawPoly").classList.remove("active");
  origImg.style.cursor = "";
  redrawPoly();
  if (commit) refresh();
}

function clearPoly() {
  polyFrac = null;
  if (polyDrawing()) finishPolyDraw(false);
  redrawPoly();
}

$("shape").addEventListener("change", () => {
  $("drawPoly").hidden = shape() !== "poly";
  if (shape() !== "poly") clearPoly();
  refresh();
});
$("drawPoly").addEventListener("click", () => { if (!polyDrawing()) startPolyDraw(); });
origImg.addEventListener("click", (e) => {
  if (!polyDrawing()) return;
  polyDraft.push(polyLayer.toFrac(e.clientX, e.clientY));
  redrawPoly();
});
origImg.addEventListener("dblclick", (e) => {
  if (polyDrawing()) { e.preventDefault(); finishPolyDraw(true); }
});
document.addEventListener("keydown", (e) => {
  if (!polyDrawing()) return;
  if (e.key === "Enter") finishPolyDraw(true);
  else if (e.key === "Escape") finishPolyDraw(false);
  else if (e.key === "Backspace") { e.preventDefault(); polyDraft.pop(); redrawPoly(); }
});
origImg.addEventListener("load", redrawPoly);
window.addEventListener("resize", redrawPoly);

$("fitSize").addEventListener("click", async () => {
  const b = await estimate({ distance_m: distM() });
  if (b) { $("size").value = Math.round(b.width_mm); $("sizeVal").textContent = (b.width_mm / 1000).toFixed(2) + " m"; refresh(); }
});
$("fitDist").addEventListener("click", async () => {
  const b = await estimate({ size_mm: sizeMm() });
  if (b) { const d = Math.min(20, b.recommended_distance_m); $("dist").value = d; $("distVal").textContent = d.toFixed(1) + " m"; refresh(); }
});
$("fitMin").addEventListener("click", async () => {
  // Smallest size that still reads, viewed from the closest distance it reads from.
  const b = await estimate({ size_mm: sizeMm() });
  if (b) {
    const w = Math.round(b.min_size_m * 1000);
    $("size").value = w; $("sizeVal").textContent = (w / 1000).toFixed(2) + " m";
    const y = b.closest_distance_m;
    $("dist").value = y; $("distVal").textContent = y.toFixed(1) + " m";
    refresh();
  }
});

let timer = null;
function debounced() { clearTimeout(timer); timer = setTimeout(refresh, 250); }

async function estimate(params) {
  if (!imageId) return null;
  const q = new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, ...extraParams(), ...params });
  const r = await fetch("/estimate?" + q.toString());
  if (!r.ok) return null;
  return r.json();
}

async function refresh() {
  if (!imageId) return;
  const b = await estimate({ size_mm: sizeMm(), distance_m: distM() });
  if (!b) return;

  $("across").textContent = b.caps_across;
  $("total").textContent = b.total_caps.toLocaleString();
  $("floor").textContent = b.min_caps_across;
  $("mindist").textContent = b.min_distance_m + " m";
  $("quality").textContent = readQuality(distM());
  $("colours").textContent = `${b.colors_used} / ${b.effective_colors}`;

  // red = the piece won't read (act now); amber = a quality hint (nice to fix)
  const warn = $("warning");
  const msg = b.warning || (!b.legible ? "Too few caps to represent this image." : "");
  warn.hidden = !msg;
  if (msg) warn.textContent = msg;
  const note = $("notice");
  note.hidden = !b.thin_hint;
  if (b.thin_hint) note.textContent = "💡 " + b.thin_hint;

  // inventory gap (have/short) and/or stock spend, shown above the BOM
  const inv = b.inventory || null;
  const it = $("invtotals");
  const lines = [];
  if (b.stock_used) {
    const s = b.stock_used;
    const cols = `${b.colors_used} colour${b.colors_used === 1 ? "" : "s"}`;
    if (s.unlimited) {
      lines.push(`assuming unlimited stock: needs ${s.used.toLocaleString()} caps`);
      $("usableNote").textContent = `unlimited stock: needs ${s.used.toLocaleString()} caps · ${cols}`;
    } else {
      lines.push(`designed from your caps: placing ${s.used} of the ${s.owned} you own`);
      // caps-I-own readout: caps qualifying + colours, both move with the slider
      $("usableNote").textContent = `using ${s.used} of ${s.owned} caps · ${cols}`;
    }
  } else {
    $("usableNote").textContent = "";
  }
  if (b.inventory_totals) {
    const t = b.inventory_totals;
    lines.push(`you own ${t.owned} caps — ${t.have} of ${t.need} needed (${(100 * t.have / Math.max(1, t.need)).toFixed(1)}%)`);
  }
  it.hidden = lines.length === 0;
  it.textContent = lines.join(" · ");

  // BOM — click a colour to isolate where those caps go (others ghosted)
  const ul = $("bom"); ul.innerHTML = "";
  $("bomcount").textContent = `${b.colors_used} colour${b.colors_used === 1 ? "" : "s"}`;
  if (highlight && !(highlight in b.bom)) highlight = null;  // colour no longer present
  for (const [hex, n] of Object.entries(b.bom)) {
    const li = document.createElement("li");
    li.className = "bomrow" + (hex === highlight ? " active" : "");
    let extra = "";
    if (inv && inv[hex]) extra = ` <span class="inv">have ${inv[hex].have} · short ${inv[hex].short}</span>`;
    li.innerHTML = `<span class="sw" style="background:${hex}"></span>${hex} <b>${n}</b>${extra}` +
      `<button class="knock" data-tip="use bare board instead of caps for this colour">⌫</button>`;
    li.addEventListener("click", () => { highlight = (highlight === hex) ? null : hex; refresh(); });
    li.querySelector(".knock").addEventListener("click", (e) => {
      e.stopPropagation();               // the row click toggles isolate, not this
      bgColors.push(hex);
      renderBgChips(); refresh();
    });
    ul.appendChild(li);
  }
  $("bomwrap").classList.toggle("isolating", !!highlight);
  $("bgholes").textContent =
    b.holes ? `${b.holes.toLocaleString()} cells left bare` : "";

  // simulation
  const q = new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, size_mm: sizeMm(), distance_m: distM(), ...extraParams() });
  if (highlight) q.set("highlight", highlight);
  curSimSrc = "/simulate?" + q.toString() + "&_=" + Date.now();
  inflightDist = distM();   // the distance this render is being made for
  document.querySelector(".simwrap").classList.add("loading");  // cleared on img load
  $("sim").src = curSimSrc;
  const tq = new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, size_mm: sizeMm(), distance_m: distM() });
  curTargetSrc = "/target?" + tq.toString() + "&_=" + Date.now();
  // printable cap map uses the same plan-shaping params (no distance needed)
  const mq = new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, size_mm: sizeMm(), ...extraParams(), format: "pdf" });
  $("capmap").href = "/capmap?" + mq.toString();
  $("palcmp").href = "/palettes?" + new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, size_mm: sizeMm(), dither: dither() }).toString();
  if (fromMyCaps() && !unlimitedStock()) {
    // the piece is sized by how many caps you own, not the slider — show the
    // real fitted mosaic (no distance shrink), so report the derived piece
    const w = (b.width_mm / 1000).toFixed(2);
    $("simhint").textContent =
      `your caps make a ${w} m piece — ${b.caps_across} across · ${b.total_caps.toLocaleString()} caps · ${b.colors_used} colours`;
  } else {
    const pct = b.apparent_pct != null ? `fills ~${b.apparent_pct}% of your view` : "";
    $("simhint").textContent =
      `${(sizeMm() / 1000).toFixed(2)} m wide, seen from ${distM().toFixed(1)} m — ${pct} · ${readQuality(distM())}`;
  }
}

// Show how many caps the scanned inventory holds (feeds the "My scanned caps"
// group and the sizing rectangle's buildability check).
let ownedTotal = 0;
(async function loadCapsCount() {
  try {
    const b = await (await fetch("/caps_count")).json();
    ownedTotal = b.count;
    $("capsCount").textContent = `(${b.count} scanned)`;
    drawPatRect();
  } catch (_) { /* leave blank */ }
})();

// Toolbar dropdown menus (Image / Size / Caps): one open at a time, and close
// when clicking outside. The left palette panel is a plain <details> — no JS.
(function toolbarMenus() {
  const drops = () => [...document.querySelectorAll("details.menu.drop")];
  for (const d of drops()) {
    d.addEventListener("toggle", () => {
      if (d.open) for (const o of drops()) if (o !== d) o.open = false;  // one at a time
    });
  }
  document.addEventListener("click", (e) => {
    for (const d of drops()) if (d.open && !d.contains(e.target)) d.open = false;
  });
})();

// Load a sample image on first open so creators see the app working immediately.
(async function loadSample() {
  try {
    const r = await fetch("/static/default.jpg");
    if (!r.ok) return;
    const blob = await r.blob();
    upload(new File([blob], "sample-lion.jpg", { type: "image/jpeg" }));
  } catch (_) { /* no sample -> start empty */ }
})();
