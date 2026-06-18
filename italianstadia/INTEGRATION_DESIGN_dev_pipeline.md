# Integration Design — Under-development stadiums: dataset + weekly pipeline + export
_Created: 2026-06-18 | Branch: main_

## Purpose
Grow and maintain the `StadiumDevelopment` dataset (planned / approved / under-
construction grounds, ≥15,000 capacity, Europe) and keep it close to reality with
a **weekly incremental refresh**. Also integrate dev venues into the export map,
colour-coded by status (like tournaments). Today the data is a hand-curated Python
list in `add_european_developments.py` (get_or_create on name) — that doesn't
scale as projects appear, advance status, or get cancelled.

## Three parts
1. **Seed file** — a reviewable JSON of dev projects (name + country + source URL +
   tentative status/capacity). Human reviews the URLs; then we import.
2. **Weekly incremental pipeline** — re-reads each project's source page, updates
   only changed fields, never clobbers manual edits (the `locked` pattern), logs a
   diff. Discovery of NEW projects stays human-curated (see "Discovery").
3. **Export integration** — a "Show under-development" mode that renders dev venues
   as status-coloured points (Planning / Approved / Under construction).

---

## Part 1 — Seed/review file

`scripts/data/dev_stadiums.json` — one object per project:
```json
{
  "name": "Stadio della Roma",
  "country": "Italy",
  "project_type": "NEW",                 // NEW | REDEVELOPMENT | EXPANSION
  "status": "APPROVED",                  // PLANNING|APPROVED|UNDER_CONSTRUCTION|ON_HOLD|COMPLETED
  "future_capacity": 55000,
  "estimated_opening": 2028,
  "source_url": "https://en.wikipedia.org/wiki/Stadio_della_Roma",
  "team": "AS Roma"                      // optional → links future_tenants
}
```
Rule: **only ≥15,000 future_capacity, Europe.** `source_url` is the field the human
reviews. lat/lon/architect/developer are filled by the pipeline from `source_url`,
so they're optional in the seed.

## Part 2 — Weekly incremental pipeline

### Command: `python manage.py refresh_developments [--dry-run] [--only NAME]`
Runs weekly via a Render cron (separate from the season scrape). Flow per project:

```
dev_stadiums.json (reviewed seed)
  → for each entry: fetch source_url (Wikipedia infobox + Wikidata)
      → parse: future_capacity, status hints, coords, architect, developer,
                estimated_opening
  → StadiumDevelopment.objects.update_or_create(name=…)  [INCREMENTAL]
      → compare scraped vs stored; update ONLY changed fields
      → SKIP if the row is locked (manual override, same flag as Stadium.locked)
      → if a project's status flips to COMPLETED → optionally promote to a real
        Stadium row (or just mark COMPLETED so the map stops showing it as "dev")
  → log a per-field diff: "Stadio della Roma: status APPROVED→UNDER_CONSTRUCTION"
```

### Why incremental (not full reload)
- **Never lose manual corrections.** Like `Stadium.locked`, add `StadiumDevelopment.locked`; the pipeline skips locked rows. Hand-fixed coords/status survive.
- **Cheap + safe.** Only diffs are written; a bad scrape can't wipe the table.
- **Auditable.** The diff log shows exactly what changed week-to-week.

### Discovery of NEW projects (the honest hard part)
You cannot fully automate "find every new project" reliably — there's no clean API.
Three tiers, best→pragmatic:
1. **Curated seed (authoritative).** You/the community add new projects to
   `dev_stadiums.json`. This is the source of truth for *which* projects exist.
2. **Assisted discovery (optional).** A monthly job scrapes a tracker
   (e.g. stadiumdb.com "under construction" / Wikipedia "List of future stadiums")
   and emails you a candidate list to review — it never auto-inserts.
3. **The weekly pipeline only REFRESHES known projects** (status/capacity/coords).

So: humans decide *what exists* (seed + assisted suggestions); the pipeline keeps
*the facts current*. That's the realistic "close to the real world" model.

### Keeping data close to reality — best practices
- **Source of truth = official + Wikipedia + Wikidata**, two-source where possible (same contract as the ownership rules in CLAUDE.md).
- **Status is the volatile field** — re-scrape weekly; it's what changes most (planning→approved→under construction→completed, or →on hold/cancelled).
- **Promote on completion**: when a project completes, it should become an operational `Stadium` (and drop off the dev map) so the two datasets don't double-count.
- **`locked` flag** for anything you hand-verify, so the refresh never regresses it.
- **Log + review**: weekly diff email; you skim it, correct anything wrong, lock it.

## Part 3 — Export integration (dev stadiums on the map)

Mirror the tournament feature (just-built): a mode that renders dev venues as
status-coloured points.
- New export param `layer=development` (default `operational`).
- Reuse the colour-point rendering from tournament mode; status palette:
  Planning `#a78bfa` (purple), Approved `#3b82f6` (blue),
  Under construction `#ff9f1c` (orange), On hold `#9ca3af` (grey).
  (Distinct from tournament green/orange/red to avoid confusion.)
- Status checkboxes (like tournament `tstatus`): Planning / Approved / Under
  construction / On hold.
- Legend shows the displayed statuses.
- Source: `StadiumDevelopment.objects.exclude(lat/lon null)` filtered by status.

### Files that will change
| File | Change |
|------|--------|
| `scripts/data/dev_stadiums.json` | New seed/review file |
| `italiastadiaapp/management/commands/refresh_developments.py` | New incremental pipeline |
| `italiastadiaapp/models.py` | `StadiumDevelopment.locked` (+ migration) |
| `italiastadiaapp/views.py` | `layer=development` branch in export assembly; dev status palette in `_dot_colour`/legend; `export_options` returns dev statuses |
| `italiastadiaapp/templates/export.html` | Layer selector + dev-status checkboxes |
| `render.yaml` | Weekly `refresh-developments` cron |
| `italiastadiaapp/tests/test_api.py` | Pipeline + export-layer tests |

## Migration safety
- New field `StadiumDevelopment.locked = BooleanField(default=False)` → safe (default).
- No destructive operations; the pipeline only `update_or_create` + field diffs.

## Rollback plan
- Disable the cron; remove the `layer=development` param handling. No data loss
  (incremental writes only). `locked` field can stay unused.

## Open decisions (for review)
1. Promote-on-complete: auto-create a `Stadium` when status→COMPLETED, or just hide? (Recommend: mark COMPLETED, hide from dev map, create the Stadium manually.)
2. Discovery tier 2 (assisted tracker scrape) now or later? (Recommend: later — start with curated seed + weekly refresh.)
3. Dev-status colours vs tournament colours — confirm the palette above reads clearly.
