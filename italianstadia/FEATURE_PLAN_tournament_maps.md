# Feature Plan — Tournament maps on the export page
_Created: 2026-06-18 | Branch: main_

## Problem / Goal
The export tool can filter by country/league/surface/ownership but **not by
tournament**, so there's no way to produce a polished, downloadable map of a
single competition's venues (e.g. "Euro 2032 host stadiums"). The owner wants to
promote tournaments (Euro 2028/2032 now; Champions League / Europa League /
Conference League finals next) with shareable maps colour-coded by venue status:
**green = CONFIRMED, orange = CANDIDATE, red = DISCARDED** (a candidate that was
later cut — e.g. when the Italian panel finalises the Euro 2032 shortlist).
Success = pick a tournament in the export, choose which statuses to show
(confirmed / candidate / discarded / all), and get a map of exactly those venues
— including under-development grounds — on the free + paid download.

It must be **generic**: adding a new tournament later requires only data edits
(the `tournaments` JSON on Stadium / StadiumDevelopment via admin), zero export
code changes.

## Scope
**In scope:**
- [ ] "Tournament" dropdown in the export filters, auto-populated from tournaments present in the data
- [ ] `tournament=<slug>` export param (matches `slugify(tournament name)`, same slug the detail page uses)
- [ ] A **status category selector** (checkboxes): Confirmed / Candidate / Discarded — default Confirmed + Candidate; "all" = tick all three. Param `tstatus=confirmed,candidate,discarded`
- [ ] New venue status value **DISCARDED** (was a candidate, later cut) — supported in the data, the detail page, and the export
- [ ] Venue set sourced from BOTH `Stadium.tournaments` AND `StadiumDevelopment.tournaments`
- [ ] Per-venue `tournament_status` (CONFIRMED / CANDIDATE / DISCARDED) carried into the render
- [ ] Badge ring colour: green (CONFIRMED) / orange (CANDIDATE) / red (DISCARDED) instead of the white ring
- [ ] Legend shows the colours for whichever statuses are displayed
- [ ] Works in preview, free (branded) and paid (clean) downloads
- [ ] When a tournament is selected, country/league/surface filters are ignored (tournament defines the set)

**Out of scope (do not touch):**
- The tournament detail page UI (only refactor its venue-building into a shared helper)
- Editing tournament data (done via admin / JSON, not here)
- Match/fixture-level data, group draws
- Any model/schema change (uses existing `tournaments` JSONField)

## Design decisions
1. **Identify a tournament by slug**, matched as `slugify(entry["tournament"]) == slug`. | Alt: numeric ID | Reason: tournaments live only as strings inside the `tournaments` JSON; the detail page + sitemap already key on `slugify(name)`. Slug keeps it generic — new tournaments need no code.
2. **One shared venue source.** Extract the venue-gathering loop currently inside `tournament_detail` into a reusable `_tournament_venues(slug)` helper returning dicts with `name, lat, lon, image_url, status, city, capacity`. Both the detail page and the export call it. | Alt: duplicate the query in the export | Reason: single source of truth — statuses/venues can't drift between page and export.
3. **Include StadiumDevelopment venues.** Tournament venue lists mix existing and future grounds; the export's normal path only queries `Stadium`. The tournament path merges both. | Alt: operational only | Reason: Euro 2032 candidates are largely redevelopments/new builds — omitting them makes the map wrong.
4. **Status as a colour ring, keep the club badge.** Draw the badge as usual but replace the white ring with a green/orange/red ring; dev venues with no club badge show a coloured filled dot. Colours: CONFIRMED `#28c76f` (green), CANDIDATE `#ff9f1c` (orange), DISCARDED `#e74c3c` (red). | Alt: grey-out discarded | Reason: red reads as "cut/out" and stays visible on dark + satellite; greyed venues vanish against the dark base.
5. **Three-way status, not binary.** The current code is binary (`CONFIRMED` else `CANDIDATE`) — in the model data, the detail page, and sorting. Generalise to an explicit set {CONFIRMED, CANDIDATE, DISCARDED}; unknown/blank → treated as CANDIDATE for back-compat. | Alt: keep binary, bolt discarded on | Reason: a clean 3-way enum avoids scattered special-cases as more statuses appear.
6. **Status category selector (multi-select).** Checkboxes Confirmed / Candidate / Discarded; the export shows only ticked statuses (default Confirmed + Candidate, so discarded venues are opt-in and don't clutter the default map). Param `tstatus=` comma list. | Alt: a single "show all / only X" radio | Reason: multi-select lets users make "confirmed only", "the ones that got cut", or "everything" maps from one control.
7. **Tournament overrides other filters.** If `tournament` is set, ignore country/league/surface/ownership. | Alt: AND them together | Reason: a tournament is an explicit, self-contained venue set; combining filters would confuse and usually yield the same or empty result.
8. **Reuse the existing colour-by mechanism.** Add `color_by="tournament_status"` so `_dot_colour` / legend flow through one code path. | Alt: special-case throughout | Reason: minimal new branching.

## Files that will change
| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/views.py` | Edit | `_tournament_venues(slug)` helper (refactor from `tournament_detail`, 3-way status); update `tournament_detail` sorting/grouping for 3 statuses; `tournament`+`tstatus` in `_parse_export_params`; tournament branch in the export stadium assembly; green/orange/red ring in `_draw_dots_and_labels`; status legend in `_build_legend_entries`; `tournaments` list in `export_options`; add `tournament`,`tstatus` to checkout `allowed_keys` |
| `italiastadiaapp/templates/tournament_detail.html` | Edit | Show DISCARDED venues in red (3-way status styling) |
| `italiastadiaapp/templates/export.html` | Edit | "Tournament" dropdown + Confirmed/Candidate/Discarded checkbox group; `_getFilters` includes `tournament`+`tstatus`; selecting a tournament disables/zeroes the other filters |
| `italiastadiaapp/tests/test_api.py` | Edit | Tests for `_tournament_venues` + `map_export?tournament=` |

## Implementation steps (bottom-up)
1. [ ] Refactor: extract `_tournament_venues(slug)` from `tournament_detail`, returning each venue's `status` as a 3-way value (CONFIRMED / CANDIDATE / DISCARDED; blank → CANDIDATE). Update the detail view + its sorting/grouping to handle 3 statuses (e.g. a status-order map) — verify the page still renders, now also showing any DISCARDED venues in red.
2. [ ] `export_options`: return `tournaments` = sorted unique `{slug, label}` from Stadium + StadiumDevelopment `tournaments` JSON.
3. [ ] `_parse_export_params`: parse `tournament` (slug) and `tstatus` (comma list → set of {confirmed,candidate,discarded}; default {confirmed,candidate}).
4. [ ] Export assembly (`_compose_export_image` / `_get_export_stadiums`): if `tournament` set, build the list from `_tournament_venues(slug)`, keep only venues whose status ∈ `tstatus`, attach `tournament_status`, set `color_by="tournament_status"`; else current path.
5. [ ] `_dot_colour` / `_draw_dots_and_labels`: ring colour by status — green `#28c76f` / orange `#ff9f1c` / red `#e74c3c`; dev venues (no badge) → filled status dot.
6. [ ] `_build_legend_entries`: one entry per DISPLAYED status (only the ticked ones) when `color_by=="tournament_status"`.
7. [ ] `export.html`: Tournament `<select>` + a Confirmed/Candidate/Discarded checkbox group (the status selector); when a tournament is set, grey out country/league/surface/ownership and omit them from `_getFilters`; include `tournament` + `tstatus`.
8. [ ] `export_checkout` `allowed_keys`: add `tournament`, `tstatus`.
9. [ ] Tests + manual check.

## PostgreSQL safety check
- [x] No new model fields — uses the existing `tournaments` JSONField on Stadium & StadiumDevelopment.
- [x] No migration required.

## Test plan
- `_tournament_venues('uefa-euro-2032')` returns >0 venues, each status ∈ {CONFIRMED, CANDIDATE, DISCARDED}, and includes at least one StadiumDevelopment venue.
- `tstatus` filtering: `?tournament=…&tstatus=confirmed` shows only confirmed; `…&tstatus=discarded` shows only the cut venues; default (no `tstatus`) = confirmed + candidate (no discarded).
- `GET /api/export/map/?tournament=uefa-euro-2032&tstatus=confirmed,candidate,discarded&labels=1` → 200 PNG with green + orange (+ red if any discarded exist); dev venues present.
- The detail page `/tournaments/uefa-euro-2032/` still renders and shows DISCARDED venues in red.
- `export_options` JSON includes a `tournaments` array with `uefa-euro-2032`.
- No-overlap / edge-disposition label rules still hold (existing placement engine).
- Manual: export Euro 2032 with each status combination; preview, free and paid all correct.

## Generic-by-design check
Adding "UEFA Champions League Final 2027" later = add a `tournaments` entry
(`{"tournament": "...", "year": 2027, "status": "CONFIRMED"|"CANDIDATE"}`) to the
relevant Stadium/StadiumDevelopment via admin. It then appears in the export
dropdown and renders automatically — **no code change**.

## Data prerequisite (done)
The tournament venue lists must be complete BEFORE the feature is useful. Migration
`0048` adds the two missing Euro 2032 candidate venues — Fiorentina's New Artemio
Franchi and the New Cagliari Stadium (both `StadiumDevelopment`, status CANDIDATE).
Going forward, completing a tournament's venue list = data edits only (admin / a
data migration), never export code.

## Rollback plan
- Remove the `tournament` param handling + dropdown; the shared `_tournament_venues`
  helper is harmless to keep. No migration to reverse.
