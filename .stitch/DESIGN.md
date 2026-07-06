# Capillisim Estimator — Design System

Extracted from the live implementation (`src/cap_mosaic/app/webapp/static/`),
then used to drive the automated improve→judge loop. Judge = Qwen vision with a
strict UI rubric; baseline score **78/100**.

## Tokens (current, de-facto)

| Token | Value | Notes |
|---|---|---|
| --bg | #12141a | page |
| --panel | #1b1e27 | cards |
| --ink | #e8eaf0 | text |
| --mut | #9aa1b2 | secondary text |
| --acc | #f2b705 | gold accent |
| --warn | #7a2130 | red banner |
| (unnamed) | ~25 hard-coded hexes | borders #333a49/#39445a/#3b4457/#4a5670/#2b3550, surfaces #141a26/#0d1117/#2a3140, link #6cf, AI indigo #4a5892 … |

- **Type sizes in use:** 11, 12, 13, 14, 15, 16, 18, 22 px — eight sizes, no scale.
- **Weights:** 400/600/700 assigned ad hoc.
- **Spacing values in use:** 3,4,5,6,7,8,9,10,12,14,16,18,22,26,34 px — no rhythm.
- **Radii in use:** 4, 6, 8, 9, 10, 12, 14 px — seven radii.
- **Componentized:** buttons (base/.btn-ai/.btn-gold), data-tip tooltips, group cards, version tiles, toast, spinner.

## Audit (be critical)

1. **Token drift.** 25+ raw hexes; three different border greys can appear in one
   viewport. Surfaces #141a26 vs #1b1e27 vs #0d1117 chosen per-component, not per role.
2. **Radius chaos.** Seven corner radii = subconscious noise. Nothing communicates
   "this is a control vs a card vs the hero surface".
3. **No spacing rhythm.** Fifteen distinct paddings; the banner, cards and groups
   breathe unevenly (flagged by the judge: "standardize vertical rhythm").
4. **No type scale.** 11px meta text is below comfortable legibility; 12px serves
   both labels and metadata; 600 vs 700 carries no meaning.
5. **Gold does too many jobs.** Primary action, focus ring, active selection,
   slider fill, checkbox fill, the caps-count badge, the inline apply link, group
   count highlight. Accent-as-everything = accent-as-nothing.
6. **Ad-hoc colours in data.** `.bom .inv` orange #e6a86c invents a colour; BOM
   active row uses link-blue for a selection state (gold's job).
7. **Flat surface hierarchy.** The hero (simulation) card carries the same visual
   weight as a stats tile.
8. **Focus visibility only on buttons.** Links, version tiles and BOM rows have
   no :focus-visible treatment.
9. **Header spends 60px on a tagline** that matters only on first visit.
10. **Judge round-2 asks:** vertical rhythm grid, 3-weight type system, accent
    discipline — systemic, not cosmetic.

## Direction

Tonal direction: **technical & dense workshop** — a precision instrument for a
physical craft. The memorable moves: a real typographic identity (no more
system-ui) and the simulation canvas staged as the hero.

- **Type** (via Google Fonts, graceful fallback):
  - Display `Space Grotesk` — h1, group headings, stat values.
  - Body `IBM Plex Sans` — everything else.
  - Numerals `IBM Plex Mono` — stats, BOM counts, slider values (tabular).
  - Scale + roles: 12 meta(mut) · 13.5 body(400) · 15 value(600) · 20 stat(700
    display) · 26 h1(700 display). Weight semantics: 400 body, 600 value/label
    emphasis, 700 display only.
- **Spacing rhythm:** `--s1..--s6` = 4/8/12/16/24/32; components pick from the
  ladder, nothing else.
- **Radii, 3 tiers:** `--r-ctl` 8 (buttons/inputs) · `--r-card` 12 (cards) ·
  `--r-hero` 16 (dropzone + sim stage).
- **Surfaces/borders as tokens:** `--surface-0` page · `--surface-1` card ·
  `--surface-2` inset wells · `--border-1` rest · `--border-2` hover/active.
  Cool darks kept deliberately: complementary tension against the warm amber
  accent and the warm cap imagery.
- **Accent discipline:** gold = primary action + active selection ONLY; indigo
  `--ai` = AI capabilities; `--link` blue = navigation/downloads; amber/red
  banners = notices. Data stays neutral; the caps-count badge and inline apply
  link stop borrowing gold.
- **Atmosphere:** hero-only — the sim stage gets a faint radial vignette and
  the one dramatic shadow; every other card stays flat and clean.
- **Motion:** one staggered load-in (columns fade+rise 300ms, 60ms apart);
  existing hover/press polish retained; transform/opacity only.

## Scores (Qwen UI judge, same rubric throughout)

| State | Score |
|---|---|
| Baseline (pre design-system) | 78 |
| Pass 1: full token system, type identity, hero stage, accent discipline | 78 |
| Pass 2: styled slider tracks/thumbs; responsive check passes at 740px | 78 |

**Loop verdict:** plateau — the stop rule fired. The judge's discrimination is
band-coarse for this genre (three visibly different UIs scored identically, and
some round-3 issues were hallucinated, e.g. a "#FF4757 accent" that never
existed). Use the judge for *finding concrete issues* (its issue lists were
consistently useful) rather than for measuring deltas; human eyes confirm the
pass-1 result is a clear visual upgrade.

## Final tokens

The `:root` block in `static/style.css` is the source of truth: surfaces
(--surface-0/1/2), borders (--border-1/2), accents (--acc gold action/selection,
--ai indigo, --link blue), rhythm (--s1..--s6 = 4/8/12/16/24/32), radii
(--r-ctl 8 / --r-card 12 / --r-hero 16), fonts (Space Grotesk display, IBM Plex
Sans body, IBM Plex Mono numerals). New CSS must pick from these; adding a raw
hex is a design-system regression.
