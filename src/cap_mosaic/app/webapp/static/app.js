"use strict";
const $ = (id) => document.getElementById(id);
const PITCH = 32; // mm
const ARCMIN = 3437.75;

let imageId = null;
let versions = [];  // [{id, label, aspect}] — Original, crops, AI edits; imageId = active
let aspect = 1;
let selFrac = null;  // {x0,y0,x1,y1} in image fractions
let highlight = null;  // BOM colour being isolated (hex), or null
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
$("dist").addEventListener("input", () => { $("distVal").textContent = distM().toFixed(1) + " m"; debounced(); });
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

// patterns from the owned inventory: land as new versions in the strip
for (const [btn, kind] of [["patGradient", "gradient"], ["patSpiral", "spiral"], ["patSunburst", "sunburst"]]) {
  $(btn).addEventListener("click", async () => {
    const b0 = $(btn); b0.disabled = true;
    try {
      const r = await fetch("/pattern?" + new URLSearchParams({ kind }));
      if (!r.ok) { toast(r.status === 404 ? "Scan some caps first — the inventory is empty." : "Pattern failed"); return; }
      const b = await r.json();
      if (!versions.length) {  // patterns can be the very first "image"
        $("imagepanel").hidden = false; $("origwrap").hidden = false; $("croptools").hidden = false;
        $("versionswrap").hidden = false; $("controls").hidden = false;
        $("stats").hidden = false; $("bomwrap").hidden = false;
      }
      addVersion(b, `Pattern ${kind}`);
      toast(`Pattern laid out from ${b.caps} of your caps`);
    } finally { b0.disabled = false; }
  });
}

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
    li.innerHTML = `<span class="sw" style="background:${hex}"></span>${hex} <b>${n}</b>${extra}`;
    li.addEventListener("click", () => { highlight = (highlight === hex) ? null : hex; refresh(); });
    ul.appendChild(li);
  }
  $("bomwrap").classList.toggle("isolating", !!highlight);

  // simulation
  const q = new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, size_mm: sizeMm(), distance_m: distM(), ...extraParams() });
  if (highlight) q.set("highlight", highlight);
  curSimSrc = "/simulate?" + q.toString() + "&_=" + Date.now();
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

// Show how many caps the scanned inventory holds (feeds the "My scanned caps" group).
(async function loadCapsCount() {
  try {
    const b = await (await fetch("/caps_count")).json();
    $("capsCount").textContent = `(${b.count} scanned)`;
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
