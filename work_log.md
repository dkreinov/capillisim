# Work log — caps-own-fit

Plan: plans/caps-own-fit-plan.md
Mode: autonomous, Opus/High. Local only (no subagents). Branch: main.

Frozen contracts:
- `usable_groups(groups, image, threshold_de, filter_k) -> list[Group]`
- `fit_caps_across(n_caps: int, aspect: float) -> int`
- `own_threshold: float` (ΔE00, default 12) on /estimate + /simulate

## Step 1 — Reproduce & confirm diagnosis (read-only) — DONE
Scratch: $CLAUDE_JOB_DIR/tmp/step1_diag.py, step1_sim.py

Diagnosis: grid sized by size slider ≫ owned caps.
- owned caps: 416, colour groups: 214
- caps_across=40 → 1817 cells, 416 filled, 1401 holes (77%), 214 distinct colours
- caps_across=80 → 7314 cells, 416 filled, 6898 holes (94%), 214 distinct
- caps_across=120 → 16491 cells, 416 filled, 16075 holes (97%), 214 distinct
- /simulate from_my_caps → HTTP 200, image/png, 308 KB (NOT a render miss)
- /estimate from_my_caps → colors_used=214 (all groups → noise), total_caps=416

Root cause confirmed: cells ≫ 416, distinct colours in the hundreds, high hole
fraction. `assign_stock` fills only ~416 cells, rest are noise/holes.
Commit: skipped (read-only).

## Step 2 — RED tests for the fit algorithm — DONE
File: tests/test_owned_fit.py (new). 4 tests.
- test_fit_caps_across_within_tolerance: grid count within ±12% of n (n=150/300/416).
- test_usable_groups_threshold_crossover: far group (ΔE~20.7) excluded at thr=12,
  included at thr=40; near group always kept.
- test_usable_groups_monotone_nondecreasing: |usable(thr)| non-decreasing.
- test_fit_path_uses_few_colours_and_fills_X_cells: fit path uses ≤ usable groups
  (3, not 6) distinct colours, fills ~X cells.
Validation: RED — ImportError (fit_caps_across / usable_groups absent). Expected.
Note: naive analytic fit undershoots for small n; Step 3 uses a small search
around the analytic estimate (within 12% for realistic X ≥ ~120).
Commit: test: Step 2 - red tests for caps-I-own fit algorithm

## Step 3 — GREEN: usable_groups + fit_caps_across — DONE
File: src/cap_mosaic/app/planner_designer.py
- usable_groups(groups, image, threshold_de, filter_k): filter_k CIELAB k-means
  centroids = colours the image needs; keep groups whose min ΔE00 (ciede2000_matrix)
  to any centroid <= threshold_de. Monotone, order-preserving.
- fit_caps_across(n_caps, aspect): analytic inverse of hex count, then small
  search window (est-4..est+7) for the caps-across whose real grid.count is
  closest to n_caps (closed form undershoots at edges).
Imports: added HEX_CELL_AREA_FACTOR, Cap, grid_for_caps_across.
Validation: test_owned_fit 4/4 pass; full suite 281 passed, 0 failed.
Commit: feat: Step 3 - usable_groups + fit_caps_across (green)

## Step 4 — Wire into the server — DONE
Files: src/cap_mosaic/app/webapp/server.py, tests/test_inventory_browser.py
- _plan(from_my_caps): now usable_groups(groups, img, own_threshold, filter_k=
  max(colors,16)) -> fit_caps_across(X, aspect) -> grid shrunk to usable-cap count
  -> plan_from_inventory over kept groups. Fallback to full stock if threshold
  excludes everything. own_threshold added to cache key.
- _own_geometry(res, plan): fitted piece overrides slider size (caps_across,
  width_mm, height_mm); panel_caps = plan.count; stock_used gains "usable".
- /estimate + /simulate gain own_threshold (ΔE00, default 12), passed through.
Validation (real caps.db, 2-tone image, size 3000):
  thr=6  colors_used=3  caps_across=2  panel=3   total=3   holes=0  (was 214/thousands/77-97% holes)
  thr=12 colors_used=15 caps_across=5  panel=23  total=21  holes=2
  thr=20 colors_used=75 caps_across=10 panel=105 total=103 holes=2
  Colours/size now scale with the slider; holes ~0; image reads.
Tests: test_own_threshold_filters_colours_and_fits_grid,
  test_own_threshold_simulate_renders. Full suite 283 passed, 0 failed.
Commit: feat: Step 4 - server: own_threshold + fit resolution for caps-I-own

## Step 6 — Docs + final green — DONE
Files: docs/ESTIMATOR.md, docs/images/caps-own-fit.png (new)
- Revised the &from_my_caps endpoint bullet: fitted-to-usable-caps + own_threshold,
  stock_used now {used, owned, usable}.
- New "Only caps I own (fit to inventory)" section: the 3-part fix (k-means needed
  colours, usable_groups dE gate + Match-tolerance slider, fit_caps_across grid).
- Before/after figure (real DB, sample photo): before 7314 cells/416 caps/214
  colours (noise) vs after 150 cells/150 caps/72 colours (reads).
Validation: grep own_threshold in ESTIMATOR.md = 3; full suite 283 passed, 0 failed.
Commit: docs: Step 6 - caps-I-own fit + threshold
Scratch deleted.

## PLAN COMPLETE
All 6 steps done, suite green (283). "Only caps I own" now fits the grid to the
usable-cap count with a live Match-tolerance (dE) slider (default 12); BOM/colours
scale with the slider instead of drowning 416 caps in a multi-thousand-cell grid.

---

# Task: UX/UI audit (Phase 1) — plans/ux-audit-plan.md
Started: 2026-07-12
Status: In Progress
Mode: autonomous / pause-between-phases

## Step 1: Environment preflight
- Status: ✅ Complete
- Summary: killed stale server (PID 11540); PATH python broken (MS Store stub) — server started with C:\Users\nishtiak\AppData\Local\Programs\Python\Python312\python.exe; HTTP 200; caps DB 416 caps; QWEEN_KEY present in repo/.env; page loads in Chrome (title + controls verified via JS — screenshots blocked, Chrome minimized, using synthetic-JS fallback per memory).
- Deviations: screenshot capture unavailable → evidence via JS state reads + server-side renders.
- Files changed: none
- Git commit: skipped

## Step 2: Control inventory checklist
- Status: ✅ Complete
- Summary: 52 controls catalogued (estimator 47, inventory 5) in plans/ux-audit-checklist.md; all JS-referenced endpoints exist; every HTML id has a JS reference (grep reconciliation clean). Orphan found: /ai_pattern endpoint with no UI (deliberate leftover), /health ops-only.
- Files changed: plans/ux-audit-checklist.md (git-ignored)
- Git commit: skipped

## Step 3: Live click-through — estimator
- Status: ✅ Complete
- Summary: 43/47 estimator rows PASS; AI rows deferred to Step 5. Findings: (1) FAIL scanner button — silent failure, success toast though camera missing, error only in flash console; (2) PARTIAL pattern-mode simhint shows slider-size cap count (8,557) not pattern-rect count (793); (3) default sample opens in red "too few caps" warning state; (4) preset silently overrides Colours field; (5) ✨ heuristic apply changes settings (incl. preset→space) with no summary; (6) first renders 2-20 s with only a dim as feedback.
- Deviations: paste/shift-click/file-picker not exercisable headless — code-verified, marked N/T.
- Files changed: plans/ux-audit-checklist.md
- Git commit: skipped

## Step 4: Inventory page + scanner path
- Status: ✅ Complete
- Summary: inventory all PASS (416 caps, filters, distance-test modal 200, arm/cancel delete verified, destructive path untouched). Scanner leg: GUIDE.md documents card + scan flow well; friction: webapp Scan button hardcodes camera 0/--auto and dies silently without camera (no error surfaced, no camera picker); CLI has --camera flag but web path doesn't expose it.
- Files changed: plans/ux-audit-checklist.md
- Git commit: skipped

## Step 5: AI features evaluation (real runs)
- Status: ✅ Complete
- Summary: 3 test images (vector lion, photographic 64-cap collage, flat smiley). AI judge: PASS — fast (3 s), 88/100, genuinely useful tips; apply-settings works + before-snapshot, BUT can set size below legibility floor (1.2 m vs 3.2 m floor) with no guard. AI simplify: inconsistent — lion improved (teal grid → solid bg) though heuristic floor unchanged 100 (GUIDE's 11,400→4,400 claim NOT reproduced); busy photo 40→40 no gain; simple smiley HARMED (97→47, floor 16→100, noisy pixel-texture bg added). Palette-prompt copy: PASS, sane prompt. Evidence PNGs in scratchpad (lion_orig/simplified, busy_photo*, simple_smiley*).
- Recommendation drafted: keep AI judge; guard apply-settings against sub-floor size; demote AI simplify to secondary with "busy backgrounds only" guidance OR lead with prompt-copy workflow; fix GUIDE claim.
- Files changed: plans/ux-audit-checklist.md
- Git commit: skipped

## Step 6: Complexity/clarity/polish audit
- Status: ✅ Complete
- Summary: 7-phase pass done. Console clean; a11y baseline good (alt-texts, labels, lang, reduced-motion, breakpoints); robustness good (400 bad upload, 404 missing id, 12 m estimate 3.3 s). Tooltip census: 51 tooltips, avg 89 chars, 9 over 150, max 368 — help-as-tooltip-wall confirmed. Verdict table drafted in plans/ux-audit-findings.md: keep everything except demote AI simplify; concentration of complexity = Caps menu; 4 High findings (scanner silent fail, AI simplify unreliable, apply-AI no floor guard, first-run warning state).
- Files changed: plans/ux-audit-findings.md
- Git commit: skipped

## Step 7: Docs/README/GitHub audit
- Status: ✅ Complete
- Summary: 31/31 image refs exist; docs already heavily illustrated. Findings: D1 Windows quickstart bash-only + Store-stub python trap (hit during preflight); D2 GUIDE oversells AI simplify; D3 radio-label drift GUIDE vs UI; D4 no hero GIF / patterns image in README; D5 no in-app docs link; D6 build-section expectation-setting for sharers. pyproject extras match install docs.
- Files changed: plans/ux-audit-findings.md

## Step 8: Synthesis + Prepare Next Phase Handoff
- Status: ✅ Complete
- Summary: findings file finalised (5 sections: ranked findings, verdict table, polish, docs audit, tickable Phase 2 scope). Handoff written (plans/ux-audit-phase-1-to-2-handoff.md); phase state updated. Phase boundary — STOP per Hard Rule #9.
- Files changed: plans/ux-audit-findings.md, plans/ux-audit-phase-1-to-2-handoff.md, plans/ux-audit-phase-state.md

## Final Summary (Phase 1)
- Total steps: 8 · Completed: 8 · Failed: 0
- Key decisions: no destructive delete test; AI eval on 3 images (portrait unavailable locally); screenshots unavailable → synthetic JS evidence
- Duration: single session 2026-07-12

---

# Task: UX audit Phase 2 fixes — plans/ux-audit-phase-2-fixes-plan.md
Started: 2026-07-12 · Mode: autonomous

## Step 1: app.js quick-fix bundle (H4 H3 M1 M3 M4)
- Status: ✅ Complete
- Summary: live-validated H4 (sample opens 3.20 m/4.4 m, no warning), M3 (colorsN disables under preset), M4 (✨ toast lists changes), M1 (pattern hint ~793 = toast 793). H3 clamp code-verified, exercised in Step 4.
- Files changed: static/app.js
- Git commit: see log

## Step 2: stats tooltips + help link (N4 N5 M6/D5)
- Status: ✅ Complete — 6 stats tips in DOM, help link → GUIDE, styled pill
- Files changed: static/index.html, static/style.css

## Step 3: scanner failure surfacing + camera picker (H1)
- Status: ✅ Complete — server returns {launched:false,error} for cam 0 and 7; UI toast shows exact error + CONNECT_PHONE hint; cam input present. Server restarted for changes.
- Files changed: server.py, static/index.html, static/app.js

## Step 4: AI simplify demotion + prompt promotion (H2)
- Status: ✅ Complete — secondary styling + honest tooltip live; real simplify run toasted score delta (52→55); H3 clamp exercised live (judge 1.2 m → clamped 3.20 m, no warning); promptBtn wired to copyPrompt.
- Files changed: static/index.html, static/app.js, static/style.css

## Step 5: render spinner (M2)
- Status: ✅ Complete — ::before spinner (gold, simspin) + "rendering…" label verified via computed styles
- Files changed: static/style.css

## Step 6: caps menu clarity (M5)
- Status: ✅ Complete — label renamed (verified live), 3 longest tooltips trimmed, zero-caps gate added
- Deviations: zero-caps branch code-verified only (real DB has 416 caps; gate function's disable+hint logic reviewed, enabled-path verified live)
- Files changed: static/index.html, static/app.js

## Step 7: console entrypoint + Windows quickstart (D1)
- Status: ✅ Complete — capillisim.exe installed, served /health 200 on :8055, killed after test; README rewritten with capillisim-first quickstart + PowerShell variant
- Files changed: pyproject.toml, README.md

## Step 8: GUIDE honesty + label sync (D2 D3)
- Status: ✅ Complete — greps: 0 stale claims, new copy present
- Files changed: docs/GUIDE.md

## Step 9: hero GIF + patterns image (D4)
- Status: ✅ Complete — zoom-walk.gif 1.2 MB, 24 frames (ping-pong 12 m→0.7 m), embedded in README §1; patterns-gallery.png added to README §1
- Files changed: docs/images/zoom-walk.gif (new), README.md

## Step 10: design gate + tests
- Status: ✅ Complete
- Summary: final live sweep — sample opens 3.20 m no warning, help link, 6 stats tips, prompt button active, simplify secondary, cam input, strictness label; console error-free. pytest: 366 passed (65 "errors" in first run were a stale locked pytest-of-nishtiak temp dir — environmental; reran with fresh --basetemp). Fixed scanner-launch test stub (poll/stdout) + added failure-path test.
- Note: tooltips >150 chars still 9 (trimmed the 3 worst incl. the 368-char one, per plan).
- Files changed: tests/test_webapp.py

## Final Summary (Phase 2)
- Total steps: 10 · Completed: 10 · Failed: 0
- Commits: aaae5e3, 5a1ca9c, 2a9db1d, b28ca16, 8613a1e, 442b19a, 0e3dc09, e9457ed, 3c16655, 3d5c7ff (main, not pushed)
- Deviations: zero-caps gate branch code-verified only (real DB has caps); tooltip >150 count unchanged beyond the 3 planned trims

---

# Task: Share-polish (screenshots/guides/example dataset/license) — plans/share-polish-plan.md
Started: 2026-07-12 · Mode: autonomous

## Step 1: build example dataset
- Status: ✅ Complete — 100/416 caps selected (farthest-point in Lab), 1 crop each, 3.3 MB, all frame paths resolve. tools/build_example_dataset.py committed.
- Files changed: examples/dataset/* (new), tools/build_example_dataset.py (new), .gitignore (anchored dataset/ to root)
- Deviation: `dataset/` gitignore pattern also matched `examples/dataset/`; anchored it to `/dataset/` so the sample is tracked while a user's own dataset/ stays ignored. Commit b066aed.

## Step 2: example-dataset fallback
- Status: ✅ Complete — throwaway server in a dataset-less CWD served count=100 + crop 200; real :8000 server still 416. server.py:42 fallback added.
- Files changed: src/cap_mosaic/app/webapp/server.py

## Step 3: refresh app-ui.jpg
- Status: ✅ Complete — regenerated via _shots/shots.js (Playwright, 860px single-column, fullPage). Visual check: "? help" pill ✓, "AI prompt" button ✓, secondary AI simplify ✓, no red warning banner ✓ (amber thin-outline notice only), current labels ✓. 860×2294.
- Deviation: _shots/ lives OUTSIDE the repo so the shots.js extension isn't tracked; only the regenerated docs/images/app-ui.jpg is committed.
- Files changed: docs/images/app-ui.jpg (+ _shots/shots.js untracked)

## Step 4: BUILD_DATASET.md
- Status: ✅ Complete — beginner dataset guide; all 4 image refs + the PDF exist. Commit a81d4ca.
- Files changed: docs/BUILD_DATASET.md

## Step 5: CREATE_IMAGE.md
- Status: ✅ Complete — beginner image guide; all 5 image refs exist (app-ui.jpg now current, zoom-walk.gif, palettes-sample.jpg, shapes.png, capmap-sample.png). 
- Files changed: docs/CREATE_IMAGE.md

## Step 6: license + example note + wiring
- Status: ✅ Complete — LICENSE (MIT) present; README links both guides (4 refs) + "Just cloned?" note + License section; examples/dataset/README.md + GUIDE pointer added. Commit cb9f810.
- Files changed: LICENSE, examples/dataset/README.md, README.md, docs/GUIDE.md

## Step 7: fallback test + green suite
- Status: ✅ Complete — 367 passed (366 + new test) with fresh basetemp. New test exercises _resolve_db() both branches (fails if fallback removed).
- Deviation: also refactored server.py (extracted _resolve_db) to make the test authentic rather than a brittle import-reload; plan Step 7 Files listed only the test.
- The 66 "errors" on a reused basetemp are the known Windows temp-dir permission flakiness (clears with a unique --basetemp), not a real failure.
- Files changed: src/cap_mosaic/app/webapp/server.py, tests/test_webapp.py

## Final Summary (Share-polish)
- Total steps: 7 · Completed: 7 · Failed: 0
- Commits: b066aed, ae3e1ed, 27138cc, a81d4ca, 757fa02, cb9f810, <this> (main, NOT pushed)
- Deviations: gitignore anchor (Step 1); server.py refactor for test (Step 7); shots.js lives outside repo so untracked (Step 3)
