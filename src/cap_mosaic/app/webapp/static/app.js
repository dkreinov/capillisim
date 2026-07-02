"use strict";
const $ = (id) => document.getElementById(id);
const PITCH = 32; // mm
const ARCMIN = 3437.75;

let imageId = null;
let originalId = null;
let originalAspect = 1;
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
function extraParams() {
  const p = { bg_color: bgColor(), dither: dither() };
  if (preset()) p.preset = preset();
  if (thicken()) p.thicken = true;
  if (realOnly()) p.real_only = true;
  if (useInv()) p.inventory = true;
  return p;
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
  if (!r.ok) { alert("upload failed"); return; }
  const b = await r.json();
  imageId = originalId = b.id;
  aspect = originalAspect = b.aspect;
  dz.querySelector("p").innerHTML = `loaded ${b.width}×${b.height}<br/><small>drop another to replace</small>`;
  setPreview(b.id);
  clearSelection();
  $("origwrap").hidden = false;
  $("croptools").hidden = false;
  $("controls").hidden = false;
  $("stats").hidden = false;
  $("bomwrap").hidden = false;
  refresh();
}

function setPreview(id) { $("orig").src = "/image?image_id=" + id + "&_=" + Date.now(); }

// --- controls ---
$("size").addEventListener("input", () => { $("sizeVal").textContent = (sizeMm() / 1000).toFixed(2) + " m"; debounced(); });
$("dist").addEventListener("input", () => { $("distVal").textContent = distM().toFixed(1) + " m"; debounced(); });
document.querySelectorAll('input[name=mode]').forEach((r) => r.addEventListener("change", refresh));
$("preset").addEventListener("change", refresh);
$("thicken").addEventListener("change", refresh);
$("realOnly").addEventListener("change", refresh);
$("dither").addEventListener("change", refresh);
$("useInv").addEventListener("change", refresh);

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
  if (!r.ok) { alert("crop failed"); return; }
  const b = await r.json();
  imageId = b.id; aspect = b.aspect;
  setPreview(b.id); clearSelection();
  refresh();
});

$("resetImg").addEventListener("click", () => {
  imageId = originalId; aspect = originalAspect;
  setPreview(originalId); clearSelection();
  refresh();
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

  const warn = $("warning");
  const msg = b.warning || (!b.legible ? "Too few caps to represent this image." : "") ;
  const hint = b.thin_hint || "";
  if (msg || hint) {
    warn.hidden = false;
    warn.textContent = [msg, hint].filter(Boolean).join("  ");
  } else { warn.hidden = true; }

  // inventory gap (have/need/short), when "Use my caps" is on
  const inv = b.inventory || null;
  const it = $("invtotals");
  if (b.inventory_totals) {
    const t = b.inventory_totals;
    it.hidden = false;
    it.textContent = `you own ${t.owned} caps — ${t.have} of ${t.need} needed (${(100 * t.have / Math.max(1, t.need)).toFixed(1)}%)`;
  } else { it.hidden = true; }

  // BOM — click a colour to isolate where those caps go (others ghosted)
  const ul = $("bom"); ul.innerHTML = "";
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
  $("sim").src = curSimSrc;
  const tq = new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, size_mm: sizeMm(), distance_m: distM() });
  curTargetSrc = "/target?" + tq.toString() + "&_=" + Date.now();
  // printable cap map uses the same plan-shaping params (no distance needed)
  const mq = new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, size_mm: sizeMm(), ...extraParams(), format: "pdf" });
  $("capmap").href = "/capmap?" + mq.toString();
  const pct = b.apparent_pct != null ? `fills ~${b.apparent_pct}% of your view` : "";
  $("simhint").textContent =
    `${(sizeMm() / 1000).toFixed(2)} m wide, seen from ${distM().toFixed(1)} m — ${pct} · ${readQuality(distM())}`;
}
