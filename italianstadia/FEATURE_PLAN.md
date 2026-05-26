# Feature Plan — Fix scraper: images, titles, girone filter, ownership
_Created: 2026-05-26 | Branch: fix/scraper-multi-league_

## Problem / Goal

Four bugs emerged when running the scraper against non-Italian leagues (Bundesliga):

1. **Wrong stadium images** — `extract_transfermarkt_stadium_image()` uses `requests.get()`, which returns 404 on Transfermarkt's JS-rendered stadium pages. The fallback `extract_wikipedia_image()` picks the first infobox `<img>`, which is often a club badge/crest rather than a stadium photo on German Wikipedia pages.

2. **`num_of_titles = 0` for all non-Italian teams** — `scrape_team()` has an explicit `if league.country.name == "Italy":` guard before the title XPath query. All Bundesliga teams (Bayern, Dortmund, etc.) get 0 titles.

3. **Girone filter shows for non-Italian division-3 leagues** — `map.js` reveals `#gironeFilter` whenever any third-division league is selected, regardless of country. Gironi (A/B/C) are an Italian Serie C concept only.

4. **Ownership classified as UNKNOWN for German stadiums** — `classify_ownership()` only knows Italian-language public-sector keywords (`comune`, `provincia`, `città metropolitana`) and Italian company suffixes (`s.r.l.`, `s.p.a`). German forms like `GmbH`, `AG`, `Stadt`, `Gemeinde` are unrecognised.

Success = Bundesliga teams have correct stadium photos, correct title counts, no girone filter visible when Germany is selected, and sensible PUBLIC/PRIVATE/MIXED ownership for all 18 stadiums.

---

## Scope

**In scope:**
- [ ] Filter badge/crest images out of `extract_wikipedia_image()` for stadiums
- [ ] Generalise `num_of_titles` scraping to any country via a nationality map
- [ ] Hide `#gironeFilter` unless the selected country is Italy (map.js)
- [ ] Expand `classify_ownership()` with German (and common European) keywords

**Out of scope (do not touch):**
- Stadium Transfermarkt pages still use `requests.get()` — not switching to Selenium (would double scrape time; Wikipedia is the authoritative source for coords/capacity anyway)
- No model/migration changes
- No new scraper data files

---

## Design decisions

1. **Badge filter uses URL path heuristics, not ML** | Alternative: image dimensions | Reason: src URLs for Wikipedia badge images reliably contain "badge", "crest", "emblem", "logo", "wappen", "escudo", "shield"; path checks are fast and zero-dependency.

2. **Nationality map for title scraping** | Alternative: scrape all `data-header__success-number` elements | Reason: summing all honours would include cups/secondary trophies; the per-award XPath `//a[@title='{Nationality} Champion']` is precise. A small static dict covers all planned Phase 2 leagues.

3. **Girone filter hidden by country, not by league** | Alternative: hide by `division_level != 3` AND `country != Italy` | Reason: country check is simpler and already tracked in filter state; if we ever add an Italian Serie C league slot, it still works correctly.

4. **Extend `classify_ownership()` in-place** | Alternative: external library / Wikidata lookup | Reason: the keyword list is small, self-contained, and easy to audit per-league; no extra dependency.

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `scripts/populate_data_from_transfermrkt.py` | Edit | Fix badge filter, title nationality map, ownership keywords |
| `italiastadiaapp/static/js/map.js` | Edit | Hide girone filter when selected country ≠ Italy |

---

## Implementation steps

1. [ ] **`classify_ownership()`** — add German public keywords (`stadt`, `gemeinde`, `landkreis`, `freistaat`, `kreis`, `stadtverwaltung`, `kommunal`) and private suffixes (`gmbh`, `ag`, `e.v.`); add common multi-language terms (`société`, `municipalité`, `ayuntamiento`) for future leagues
2. [ ] **`extract_wikipedia_image()`** — add `_is_badge_image(src)` helper that returns `True` when src contains any of: `badge`, `crest`, `emblem`, `logo`, `wappen`, `escudo`, `shield`, `blason`; skip those images in all three extraction methods
3. [ ] **`scrape_team()` — title scraping** — replace `if league.country.name == "Italy":` block with a `NATIONALITY_MAP` dict (`{"Italy": "Italian", "Germany": "German", "England": "English", ...}`) and dynamic XPath `//a[@title='{nationality} Champion']/span[@class='data-header__success-number']`; keep `num_of_titles = 0` as fallback when country not in map or element not found
4. [ ] **`map.js` — girone filter** — in `applyFilters()` and wherever the league filter is populated, show `#gironeFilter` only when `selectedCountry === "Italy"` (or `selectedCountry === ""`); hide and reset value to `""` otherwise

---

## PostgreSQL safety check

No model changes — N/A.

---

## Test plan

**Automated (add to `test_views.py` or a new `test_scraper.py`):**
- `classify_ownership("Stadt München")` → `"PUBLIC"`
- `classify_ownership("Allianz Arena München Stadion GmbH")` → `"PRIVATE"`
- `classify_ownership("Hamburger SV e.V.")` → `"PRIVATE"`
- `classify_ownership("City of Frankfurt GmbH")` → public keyword wins unless private is also present → `"MIXED"`
- Existing Italian ownership tests still pass

**Manual (after scrape re-run):**
- Open map → select Germany → confirm Girone filter is hidden
- Open map → select Italy → confirm Girone filter is visible
- After re-scrape: Bundesliga team pages show correct `num_of_titles` for Bayern (≥ 30), BVB (≥ 8)
- After re-scrape: stadium detail pages show stadium photos, not club crests

---

## Rollback plan

- Pure Python/JS changes; no migrations
- `git revert` the single commit on `fix/scraper-multi-league`
- Re-run scraper to restore previous DB values: `python manage.py scrape_season --league bundesliga --year 2025`
