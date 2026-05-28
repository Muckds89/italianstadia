# Feature Plan — Scraper Data Quality: Coords Fallback, Ownership, Attendance, Titles
_Created: 2026-05-28 | Branch: fix/scraper-data-quality_

## Problem / Goal

Four data quality gaps found by running the Primeira Liga scrape:

1. **`num_of_titles = 0` for all Portuguese clubs** — `NATIONALITY_MAP["Portugal"] = "Portuguese"` but TM's XPath uses the typo `"Portugese Champion"` (documented in CLAUDE.md, never fixed in code).
2. **Missing coordinates** — when Wikipedia has no geo data, `latitude`/`longitude` are NULL and the stadium is invisible on the map. No fallback existed.
3. **JSON `owner_raw` fallback not wired** — the JSON data files support `stadium.owner_raw` as a last-resort for stadiums missing a Wikipedia owner infobox row, but `scrape_stadium()` was ignoring it.
4. **`clean_int()` stores 0 for missing attendance** — `0` is not valid; should be `None`.

---

## Scope

**In scope:**
- [x] Fix `NATIONALITY_MAP["Portugal"]` → `"Portugese"` (TM's documented typo)
- [x] Add `_nominatim_lookup()` coordinate fallback via OSM Nominatim API
- [x] Wire JSON `owner_raw` fallback in `scrape_stadium()` using `first_valid()`
- [x] Fix `clean_int()`: return `None` for parsed value of `0`
- [x] Update `CLAUDE.md` — XPath patterns, data quality rules, scraper data files section

**Out of scope:**
- No model changes
- No new ownership keywords (handled in `fix/ownership-attendance-data-quality`)

---

## Files changed

| File | Change type | Why |
|------|-------------|-----|
| `scripts/populate_data_from_transfermrkt.py` | Edit | All 4 code fixes |
| `CLAUDE.md` | Edit | XPath patterns, data quality rules, owner_raw docs |

---

## Rollback plan

Pure Python changes, no migration. `git revert` the single commit on this branch.
