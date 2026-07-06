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
