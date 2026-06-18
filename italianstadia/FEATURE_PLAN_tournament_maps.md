# Feature Plan — Tournament maps on the export page
_Created: 2026-06-18 | Branch: main_

## Problem / Goal
The export tool can filter by country/league/surface/ownership but **not by
tournament**, so there's no way to produce a polished, downloadable map of a
single competition's venues (e.g. "Euro 2032 host stadiums"). The owner wants to
promote tournaments (Euro 2028/2032 now; Champions League / Europa League /
Conference League finals next) with shareable maps that match the tournament
detail page: **green = CONFIRMED venue, orange = CANDIDATE venue**. Success =
pick a tournament in the export, get a map of exactly its venues — including
under-development grounds — colour-coded by status, on the free + paid download.

It must be **generic**: adding a new tournament later requires only data edits
(the `tournaments` JSON on Stadium / StadiumDevelopment via admin), zero export
code changes.

## Scope
**In scope:**
- [ ] "Tournament" dropdown in the export filters, auto-populated from tournaments present in the data
- [ ] `tournament=<slug>` export param (matches `slugify(tournament name)`, same slug the detail page uses)
- [ ] Venue set sourced from BOTH `Stadium.tournaments` AND `StadiumDevelopment.tournaments`
- [ ] Per-venue `tournament_status` (CONFIRMED / CANDIDATE) carried into the render
- [ ] Badge ring colour: green (CONFIRMED) / orange (CANDIDATE) instead of the white ring
- [ ] Legend shows green=Confirmed / orange=Candidate when a tournament is selected
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
4. **Status as a colour ring, keep the club badge.** Draw the badge as usual but replace the white ring with a green/orange ring; dev venues with no club badge show a green/orange filled dot. | Alt: recolour the whole dot, drop badges | Reason: keeps club/venue identity while encoding status, matching the detail page's semantics.
5. **Tournament overrides other filters.** If `tournament` is set, ignore country/league/surface/ownership. | Alt: AND them together | Reason: a tournament is an explicit, self-contained venue set; combining filters would confuse and usually yield the same or empty result.
6. **Reuse the existing colour-by mechanism.** Add `color_by="tournament_status"` so `_dot_colour` / legend already flow through one code path. | Alt: special-case throughout | Reason: minimal new branching.

## Files that will change
| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/views.py` | Edit | `_tournament_venues(slug)` helper (refactor from `tournament_detail`); `tournament` in `_parse_export_params`; tournament branch in the export stadium assembly; status-ring in `_draw_dots_and_labels`; green/orange in `_build_legend_entries`; `tournaments` list in `export_options`; add `tournament` to checkout `allowed_keys` |
| `italiastadiaapp/templates/export.html` | Edit | "Tournament" dropdown at the top of Filters; `_getFilters` includes `tournament`; selecting one visually disables/zeroes the other filters |
| `italiastadiaapp/tests/test_api.py` | Edit | Tests for `_tournament_venues` + `map_export?tournament=` |

## Implementation steps (bottom-up)
1. [ ] Refactor: extract `_tournament_venues(slug)` from `tournament_detail`; have the view call it (no behavioural change — verify the page is identical).
2. [ ] `export_options`: return `tournaments` = sorted unique `{slug, label}` from Stadium + StadiumDevelopment `tournaments` JSON.
3. [ ] `_parse_export_params`: parse `tournament` (slug string, sanitised).
4. [ ] Export assembly (`_compose_export_image` / `_get_export_stadiums`): if `tournament` set, build the stadium list from `_tournament_venues(slug)`, attach `tournament_status`, set `color_by="tournament_status"`; else current path.
5. [ ] `_dot_colour` / `_draw_dots_and_labels`: green `#28c76f` ring for CONFIRMED, orange `#ff9f1c` for CANDIDATE; dev venues (no badge) → filled status dot.
6. [ ] `_build_legend_entries`: green=Confirmed / orange=Candidate entries when `color_by=="tournament_status"`.
7. [ ] `export.html`: Tournament `<select>` + JS; when set, grey out country/league/surface/ownership and omit them from `_getFilters`.
8. [ ] `export_checkout` `allowed_keys`: add `tournament`.
9. [ ] Tests + manual check.

## PostgreSQL safety check
- [x] No new model fields — uses the existing `tournaments` JSONField on Stadium & StadiumDevelopment.
- [x] No migration required.

## Test plan
- `_tournament_venues('uefa-euro-2032')` returns >0 venues, each with a status in {CONFIRMED, CANDIDATE}, and includes at least one StadiumDevelopment venue.
- `GET /api/export/map/?tournament=uefa-euro-2032&labels=1` → 200 PNG; render contains green + orange badges; dev venues present.
- `export_options` JSON includes a `tournaments` array with `uefa-euro-2032`.
- No-overlap / edge-disposition label rules still hold (existing placement engine).
- Manual: export Euro 2032 → confirmed green, candidates orange, future stadiums shown; preview, free and paid all correct.

## Generic-by-design check
Adding "UEFA Champions League Final 2027" later = add a `tournaments` entry
(`{"tournament": "...", "year": 2027, "status": "CONFIRMED"|"CANDIDATE"}`) to the
relevant Stadium/StadiumDevelopment via admin. It then appears in the export
dropdown and renders automatically — **no code change**.

## Rollback plan
- Remove the `tournament` param handling + dropdown; the shared `_tournament_venues`
  helper is harmless to keep. No migration to reverse.
