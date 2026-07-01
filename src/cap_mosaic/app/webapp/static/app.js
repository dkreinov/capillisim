"use strict";
const $ = (id) => document.getElementById(id);
const PITCH = 32; // mm
const ARCMIN = 3437.75;

let imageId = null;
let aspect = 1;

function mode() {
  return document.querySelector('input[name=mode]:checked').value;
}
function sizeMm() { return Number($("size").value); }
function distM() { return Number($("dist").value); }

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

async function upload(file) {
  const fd = new FormData();
  fd.append("file", file);
  const r = await fetch("/upload", { method: "POST", body: fd });
  if (!r.ok) { alert("upload failed"); return; }
  const b = await r.json();
  imageId = b.id;
  aspect = b.aspect;
  dz.querySelector("p").innerHTML = `loaded ${b.width}×${b.height}<br/><small>drop another to replace</small>`;
  $("controls").hidden = false;
  $("stats").hidden = false;
  $("bomwrap").hidden = false;
  refresh();
}

// --- controls ---
$("size").addEventListener("input", () => { $("sizeVal").textContent = (sizeMm() / 1000).toFixed(2) + " m"; debounced(); });
$("dist").addEventListener("input", () => { $("distVal").textContent = distM().toFixed(1) + " m"; debounced(); });
document.querySelectorAll('input[name=mode]').forEach((r) => r.addEventListener("change", refresh));

$("fitSize").addEventListener("click", async () => {
  const b = await estimate({ distance_m: distM() });
  if (b) { $("size").value = Math.round(b.width_mm); $("sizeVal").textContent = (b.width_mm / 1000).toFixed(2) + " m"; refresh(); }
});
$("fitDist").addEventListener("click", async () => {
  const b = await estimate({ size_mm: sizeMm() });
  if (b) { const d = Math.min(20, b.recommended_distance_m); $("dist").value = d; $("distVal").textContent = d.toFixed(1) + " m"; refresh(); }
});

let timer = null;
function debounced() { clearTimeout(timer); timer = setTimeout(refresh, 250); }

async function estimate(params) {
  if (!imageId) return null;
  const q = new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, ...params });
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
  if (b.warning || !b.legible) {
    warn.hidden = false;
    warn.textContent = b.warning || "Too few caps to represent this image.";
  } else { warn.hidden = true; }

  // BOM
  const ul = $("bom"); ul.innerHTML = "";
  for (const [hex, n] of Object.entries(b.bom)) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="sw" style="background:${hex}"></span>${hex} <b>${n}</b>`;
    ul.appendChild(li);
  }

  // simulation
  const q = new URLSearchParams({ image_id: imageId, mode: mode(), pitch_mm: PITCH, size_mm: sizeMm(), distance_m: distM() });
  $("sim").src = "/simulate?" + q.toString() + "&_=" + Date.now();
  $("simhint").textContent = `at ${(sizeMm() / 1000).toFixed(2)} m wide, seen from ${distM().toFixed(1)} m — ${readQuality(distM())}`;
}
