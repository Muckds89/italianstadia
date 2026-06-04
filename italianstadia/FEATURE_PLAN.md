# Feature Plan — Country → League combined picker
_Created: 2026-06-04 | Branch: feature/country-league-picker_

---

## Problem / Goal

The current filter bar has two independent `<select>` elements — "All countries" and
"All leagues" — that sit side by side. This wastes space and the relationship between
them is invisible to the user (you have to know to pick a country first). The goal is a
single button that, when clicked, opens a panel listing countries; hovering (desktop) or
tapping (mobile) a country reveals its leagues inline as a submenu. Selecting a league
applies both filters at once and closes the panel. The UX should be clear enough that no
tooltip or label is needed.

Success: one compact button replaces two dropdowns; all existing filter, zoom, girone,
sessionStorage, and clear-button behaviour is preserved unchanged.

---

## Scope

**In scope:**
- [ ] Custom `#countryLeaguePicker` visual component (button + panel + submenu)
- [ ] Desktop: hover country row → leagues appear inline as a submenu
- [ ] Mobile: tap country row → leagues toggle open below it
- [ ] Clicking a country name alone applies country filter (no specific league)
- [ ] Clicking a league applies country + league filters together
- [ ] Picker label updates to reflect active selection ("Italy — Serie A")
- [ ] Clear-filters button resets picker label back to "All countries"
- [ ] sessionStorage save / restore updates picker label correctly
- [ ] CSS consistent with dark navbar theme

**Out of scope (do not touch):**
- Girone filter (`#gironeFilter`) — stays as a standalone select, no change
- Ownership filter — no change
- Stadium filter — no change
- Development mode filters — no change
- `stadium-detail-map.js` — no change
- Any model, view, or URL change

---

## Design decisions

1. **Keep hidden `<select>` elements as the data model.**
   All map.js logic reads `countryFilter.value`, `leagueFilter.value`, and listens for
   `"change"` events on both. Rather than rewriting all those references, the hidden
   selects stay in the DOM (`display:none`). The visual picker only syncs values and fires
   `new Event("change")` on the target select. Zero changes to existing event-handler logic.
   Alternative: replace selects with JS variables. Rejected: would require editing 15+
   call sites in map.js, high risk of regression.

2. **Picker reads from the hidden selects — no parallel data structure.**
   `buildPickerUI()` iterates `countryFilter.options` to build country rows, and for each
   country pre-fetches its leagues by temporarily calling `populateLeagueFilter(country)`.
   This means the picker is always in sync with the same data driving filters.
   Alternative: build a separate `countriesData` object. Rejected: duplication.

3. **Submenu pattern: accordion (inline expand) for both desktop and mobile.**
   A CSS side-panel (`position: absolute; left: 100%`) disappears off screen on mobile.
   An accordion (tap country → leagues slide down below) works universally.
   On wider viewports the panel is wide enough to show country + leagues side by side.
   Alternative: pure hover submenu. Rejected: hover has no equivalent on touch devices.

4. **Click-outside closes the panel.**
   `document.addEventListener("click")` with a guard checking if the click target is
   inside `#countryLeaguePicker`. Standard pattern; no library needed.

5. **Picker label format:**
   - No filter active: "All countries"
   - Country only: "Italy"
   - Country + league: "Italy — Serie A"

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/templates/index.html` | Edit | Add picker markup; hide existing country/league selects |
| `italiastadiaapp/static/css/styles.css` | Edit | Add `.clp-*` component styles |
| `italiastadiaapp/static/js/map.js` | Edit | Add `buildPickerUI()`, `updatePickerLabel()`; hook into populate functions, `restoreFilterState()`, and `clearFiltersBtn` |

---

## Implementation steps

1. [ ] **CSS** — add `.clp-wrap`, `.clp-trigger`, `.clp-panel`, `.clp-country-row`,
   `.clp-league-row` styles. Panel: `position:absolute`, dark bg matching navbar,
   `z-index:9999`. Country rows: hover highlight. League rows: indented + accent colour.
   Mobile breakpoint (`≤768px`): full-width panel, accordion layout.

2. [ ] **HTML** (`index.html`) — insert `<div id="countryLeaguePicker">` before the
   existing selects. Add `style="display:none"` to `#countryFilter` and `#leagueFilter`.

3. [ ] **`buildPickerUI()`** (`map.js`) — reads `countryFilter.options` to build country
   rows; for each country fetches its leagues, then stores the data on row elements.
   Attaches hover (desktop) and click (mobile) listeners. Calls `updatePickerLabel()`.

4. [ ] **`updatePickerLabel()`** (`map.js`) — sets the button label from
   `countryFilter.value` and `leagueFilter.value`.

5. [ ] **Wire picker interactions** (`map.js`) — country click/hover: set `countryFilter.value`,
   dispatch `change`; league click: set both selects, dispatch `change` on `leagueFilter`.
   Click-outside listener closes panel.

6. [ ] **Hook into `populateCountryFilter()`** (`map.js`) — call `buildPickerUI()` at the
   end so the picker rebuilds whenever the country list changes.

7. [ ] **Hook into `restoreFilterState()`** (`map.js`) — call `updatePickerLabel()` after
   state is restored.

8. [ ] **Hook into `clearFiltersBtn` handler** (`map.js`) — call `updatePickerLabel()`
   after reset.

9. [ ] **Smoke test** all combinations in the test plan.

---

## PostgreSQL safety check

No model changes. Not applicable.

---

## Test plan

**Manual smoke test:**

| Action | Expected |
|--------|----------|
| Open map fresh | Picker shows "All countries", tier-1 badges from all countries |
| Click picker button | Panel opens with country list |
| Hover/tap "Italy" | Serie A / B / C appear |
| Click "Italy" (country only) | Label → "Italy", map zooms to Italy, all tiers shown |
| Click "Italy → Serie A" | Label → "Italy — Serie A", only Serie A badges |
| Click "Italy → Serie C" | Girone filter appears, label → "Italy — Serie C" |
| Click "Clear filters" | Label → "All countries", girone hidden, Europe bounds |
| Navigate away and Back | Picker label matches saved filter state |
| Change country while league active | League resets, label updates |

**Automated:**
- `pytest italiastadiaapp/tests/ -v` — all existing tests green (no model/view changes)
- `python manage.py check` — 0 issues

---

## Rollback plan

Frontend-only changes. No migration needed.

```bash
git checkout main -- italiastadiaapp/templates/index.html
git checkout main -- italiastadiaapp/static/css/styles.css
git checkout main -- italiastadiaapp/static/js/map.js
```

---

# Feature Plan — Sprint 3: Badge markers, UEFA ordering, European rebrand
_Created: 2026-06-03 | Branch: feature/badge-markers_

## Problem / Goal

The map currently shows identical coloured circles for every team. This sprint replaces
them with team badge `DivIcon` markers, adds sensible default visibility (top-flight
only), and applies UEFA 5-year coefficient ordering throughout the UI. The ranking is
fetched from Wikipedia's UEFA coefficient page and stored in the `Country` model — not
hardcoded — so a single management command refreshes the entire ordering each summer
when UEFA publishes new coefficients. The site is also rebranded "Stadiums of Europe"
and the map recentred on continental Europe.

Success: opening the map shows top-flight badges for every country centred on continental
Europe. Selecting Italy reveals all Italian tiers with visual hierarchy (Serie B/C smaller
and semi-transparent). Selecting Serie B explicitly brings those badges to full size and
prominence while Serie A shrinks back. The ranking refreshes in < 30s via one command.

---

## Scope

**In scope:**
- [ ] `Country.uefa_rank` field + migration
- [ ] Management command `update_uefa_ranking` — scrapes Wikipedia, writes to DB
- [ ] GeoJSON API: expose `country_rank` in `teams[]` properties
- [ ] Replace `L.circleMarker` with `L.marker(L.divIcon)` — team badge as icon
- [ ] Fallback for missing badge: coloured circle
- [ ] Three-state marker visibility driven by active filters (see Design decisions §3)
- [ ] Tier z-index stacking + size + opacity reflect the "active" tier
- [ ] map.js country-rank ordering built from GeoJSON data (not hardcoded)
- [ ] `_available_countries()` orders by `Country.uefa_rank` from DB
- [ ] Rebrand "Stadiums of Italy" → "Stadiums of Europe" across all templates
- [ ] Recentre map on continental Europe: `[47.5, 8.0]` zoom 4

**Out of scope (do not touch):**
- Development mode markers (no team badge — keep coloured circles)
- `stadium-detail-map.js`
- Any other model changes
- "Show all tiers" toggle — removed; lower tiers surface automatically via filters

---

## Design decisions

1. **`Country.uefa_rank` in DB, not hardcoded in JS/Python.**
   The ranking changes each summer. Storing it in the DB means one management command
   (`update_uefa_ranking`) refreshes everything: list-page dropdowns, map legend, and
   map marker ordering — without touching code.
   Alternative: JSON file in `scripts/data/`. Rejected: can't be queried in ORM, would
   still require a code-path to load it.

2. **Scrape source: Wikipedia UEFA coefficient table.**
   URL: `https://en.wikipedia.org/wiki/UEFA_coefficient`
   Reasons: plain HTML table (no JS rendering, parseable with `requests` + `bs4` already
   in the project), stable URL, reliable formatting. UEFA's own site is React-rendered
   and requires Selenium.
   Country name mismatches (Wikipedia vs our `Country.name`) handled by a small lookup
   dict inside the command. Unmatched entries are logged as WARNING for manual review.

3. **GeoJSON exposes `country_rank` per team.**
   Each team dict in `teams[]` already has `country` from `t.league.country.name`.
   Adding `country_rank: t.league.country.uefa_rank` costs zero extra queries
   (country is already `select_related`). map.js builds its sort map from this data
   at fetch time — no hardcoded constant anywhere in JS.

4. **Marker visual state — three rules, applied in priority order:**

   | Filter state | "Active" markers | "Context" markers | Hidden |
   |---|---|---|---|
   | No filter | Tier-1 teams, all countries | — | Tier 2 + 3 (all countries) |
   | Country selected, no league | All tiers of that country | — | Other countries |
   | League selected (any tier) | Teams in that league | Same-country other tiers | Other countries |

   Visual encoding per state:

   | Role | Size | Opacity | `zIndexOffset` |
   |---|---|---|---|
   | Active | 32 px | 1.0 | 2000 |
   | Context tier 2 | 24 px | 0.65 | 500 |
   | Context tier 3 | 20 px | 0.45 | 100 |
   | Hidden | — | — | removed |

   Key invariant: **the explicitly selected league always wins regardless of its tier.**
   Selecting "Serie B" promotes Serie B to 32 px / 1.0 opacity while Serie A demotes to
   context size — the user's intent is always visually honoured.

   No "Show all tiers" toggle — lower tiers surface automatically via country/league filters.

5. **`marker.setOpacity()` + icon swap for size change** — when filter state changes,
   re-create the DivIcon with the correct size class and call `setOpacity`. Both are
   O(n) over visible markers; acceptable at 170 stadiums.

6. **Map centre** `[47.5, 8.0]` zoom 4 — southern Germany/Switzerland, balances the
   arc from England to Turkey without Scandinavia bias.

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/models.py` | Edit | Add `Country.uefa_rank` IntegerField |
| `italiastadiaapp/migrations/` | New | Migration for `Country.uefa_rank` |
| `italiastadiaapp/management/commands/update_uefa_ranking.py` | New | Scrape + save ranking |
| `italiastadiaapp/views.py` | Edit | `_available_countries()` + `country_rank` in GeoJSON |
| `italiastadiaapp/static/js/map.js` | Edit | Badge markers, tier toggle, opacity, UEFA sort from GeoJSON |
| `italiastadiaapp/static/css/styles.css` | Edit | `.badge-marker` styles |
| `italiastadiaapp/templates/index.html` | Edit | Rebrand + tier toggle control |
| `italiastadiaapp/templates/stadium_list.html` | Edit | `<title>` rebrand |
| `italiastadiaapp/templates/team_list.html` | Edit | `<title>` rebrand |
| `italiastadiaapp/templates/city_list.html` | Edit | `<title>` rebrand |
| `italiastadiaapp/templates/team_detail.html` | Edit | `<title>` rebrand |

---

## Implementation steps

1. [ ] **Model — add `Country.uefa_rank`**
   ```python
   class Country(models.Model):
       name = models.CharField(max_length=255, unique=True)
       code = models.CharField(max_length=2, unique=True)
       uefa_rank = models.IntegerField(null=True, blank=True)
   ```

2. [ ] **Migration** — `python manage.py makemigrations` then `migrate`.
   Safe: nullable IntegerField, existing rows get NULL.

3. [ ] **Management command** — `italiastadiaapp/management/commands/update_uefa_ranking.py`

   Skeleton:
   ```python
   from django.core.management.base import BaseCommand
   import requests
   from bs4 import BeautifulSoup
   from italiastadiaapp.models import Country

   # Wikipedia country names → our Country.name values
   NAME_MAP = {
       "England": "England", "Italy": "Italy", "Germany": "Germany",
       "Spain": "Spain", "France": "France", "Portugal": "Portugal",
       "Netherlands": "Netherlands", "Scotland": "Scotland",
       "Belgium": "Belgium", "Turkey": "Turkey",
   }

   class Command(BaseCommand):
       help = "Fetch UEFA 5-year country coefficients from Wikipedia and update Country.uefa_rank"

       def handle(self, *args, **options):
           url = "https://en.wikipedia.org/wiki/UEFA_coefficient"
           soup = BeautifulSoup(requests.get(url, timeout=15).text, "html.parser")
           # Find the "Country coefficients" table — parse rank and association name
           # For each row: map name → Country, set uefa_rank, save
           # Log WARNING for any unmapped association
           ...
   ```

   Usage: `python manage.py update_uefa_ranking`
   Run once after UEFA publish new coefficients each summer (typically June/July).

4. [ ] **Seed initial ranking** — run the command immediately after migration so the DB
   is not NULL before deployment:
   `python manage.py update_uefa_ranking`

5. [ ] **GeoJSON API — add `country_rank` to team dict** in `stadiums_geojson` view
   (no new query — `league__country` is already `select_related`):
   ```python
   {
       "id": t.id,
       "name": t.name,
       ...
       "country": t.league.country.name if t.league and t.league.country else city_country,
       "country_rank": t.league.country.uefa_rank if t.league and t.league.country else None,
   }
   ```

6. [ ] **`_available_countries()`** — order by `Country.uefa_rank`:
   ```python
   def _available_countries():
       return list(
           League.objects
           .select_related("country")
           .values_list("country__name", flat=True)
           .distinct()
           .order_by("country__uefa_rank", "country__name")
       )
   ```
   Note: `country__name` as secondary sort handles any ties or NULLs gracefully.

7. [ ] **CSS — badge marker styles** in `styles.css`
   ```css
   .badge-marker { border-radius: 50%; border: 2px solid rgba(255,255,255,0.8);
                   box-shadow: 0 1px 5px rgba(0,0,0,0.7);
                   transition: transform 0.15s; object-fit: contain; display: block; }
   .badge-marker:hover { transform: scale(1.3); }
   .tier-1 .badge-marker { width: 32px; height: 32px; }
   .tier-2 .badge-marker { width: 24px; height: 24px; }
   .tier-3 .badge-marker { width: 20px; height: 20px; }
   ```

8. [ ] **JS — build `countryRankMap` from GeoJSON data** after fetch (replaces hardcoded constant):
   ```js
   const countryRankMap = {};  // populated after /api/stadiums/ loads
   data.features.forEach(f => {
       f.properties.teams.forEach(t => {
           if (t.country && t.country_rank != null)
               countryRankMap[t.country] = t.country_rank;
       });
   });
   ```

9. [ ] **JS — `createBadgeIcon(imageUrl, tier)`** helper:
   - Returns `L.divIcon` with `<img class="badge-marker">` if `imageUrl` is set
   - Falls back to `<div class="badge-marker-fallback">` coloured circle

10. [ ] **JS — replace `L.circleMarker` with `L.marker` + DivIcon**
    - `zIndexOffset`: tier 1 → 1000, tier 2 → 500, tier 3 → 0
    - Remove `mouseover/mouseout` colour handlers (hover is now pure CSS)
    - Keep all `.on("click")` logic unchanged

11. [ ] **JS — update `applyFilters()`** for three visual states:
    ```js
    markers.forEach(marker => {
        const inSelectedLeague = selectedLeague && marker.leagues.some(l => l.id === selectedLeague);
        const inSelectedCountry = selectedCountry && marker.leagues.some(l => l.country === selectedCountry);
        const isTopTier = marker.primaryLeague?.divisionLevel === 1;

        // Determine role
        let role; // "active" | "context-2" | "context-3" | "hidden"

        if (!selectedCountry && !selectedLeague) {
            role = isTopTier ? "active" : "hidden";
        } else if (selectedLeague) {
            if (inSelectedLeague) role = "active";
            else if (inSelectedCountry) {
                role = marker.primaryLeague?.divisionLevel === 2 ? "context-2" : "context-3";
            } else role = "hidden";
        } else { // country only
            if (!inSelectedCountry) role = "hidden";
            else if (isTopTier) role = "active";
            else role = marker.primaryLeague?.divisionLevel === 2 ? "context-2" : "context-3";
        }

        // Apply also ownership/stadium/girone filters on top
        if (role === "hidden" || !ownershipMatches || !gironeMatches || !stadiumMatches) {
            map.removeLayer(marker); return;
        }

        const cfg = {
            "active":    { opacity: 1.0, zOffset: 2000, sizeClass: "sz-32" },
            "context-2": { opacity: 0.65, zOffset: 500,  sizeClass: "sz-24" },
            "context-3": { opacity: 0.45, zOffset: 100,  sizeClass: "sz-20" },
        }[role];

        marker.setOpacity(cfg.opacity);
        marker.setZIndexOffset(cfg.zOffset);
        marker.setIcon(createBadgeIcon(marker.primaryTeam, cfg.sizeClass));
        marker.addTo(map);
        visibleMarkers.push(marker);
    });
    ```

13. [ ] **JS — `updateLegend()` + `populateCountryFilter()`** sort by `countryRankMap`

14. [ ] **JS — recentre** initial `setView([47.5, 8.0], 4)` and reset handler

15. [ ] **HTML — `index.html`**: rebrand `<title>` + `.navbar-brand` (no tier toggle needed)

16. [ ] **Templates** — rebrand `<title>` in stadium/team/city list pages and team_detail

17. [ ] **Tests** — `makemigrations --check` must pass; all 20 existing tests green;
    add one test for `Country.uefa_rank` field existence

18. [ ] **Smoke test**: map centre, badge icons, tier toggle, grey-out, legend order,
    country dropdown order, navbar brand across all pages

---

## PostgreSQL safety check

- [x] `Country.uefa_rank` is `IntegerField(null=True, blank=True)` — safe nullable add
- [x] No `SmallIntegerField` — `IntegerField` handles rank values 1–55+
- [x] No scraped CharField length risk — rank is an integer
- [x] No new FK fields

---

## Test plan

**Automated:**
- `pytest italiastadiaapp/tests/ -v` — all 20 existing + 1 new = 21 must pass
- `python manage.py makemigrations --check` — no pending migrations

**New test** (`test_models.py`):
```python
def test_country_uefa_rank_field():
    country = Country(name="England", code="GB", uefa_rank=1)
    assert country.uefa_rank == 1
```

**Manual:**
- [ ] `python manage.py update_uefa_ranking` runs without error, logs rank for each country
- [ ] Map opens at zoom 4 centred on continental Europe
- [ ] Default: tier-1 badges from ALL countries visible (England, Italy, Germany, France, Portugal…)
- [ ] Tier 2/3 are hidden with no filter active
- [ ] Select "Italy": Serie A (32 px full), Serie B (24 px 65%), Serie C (20 px 45%), other countries hidden
- [ ] Select "Serie B" (after or instead of country): Serie B badges 32 px / full opacity / on top; Serie A shrinks to 24 px / 65%; Serie C 20 px / 45%
- [ ] Select "Premier League": PL badges on top full; other English tiers dimmed; other countries hidden
- [ ] Clearing filters returns to default (all tier-1, all countries)
- [ ] Country dropdown: England first, Italy second, Germany third
- [ ] Legend: England leagues top, Italy next
- [ ] Navbar brand reads "Stadiums of Europe" on all pages

---

## Deferred — UEFA club coefficients

**Decision:** not included in this sprint. Implement as a standalone follow-on after Sprint 3 ships.

**What it is:** UEFA publishes 5-year club coefficients for every club that has played in
CL / EL / Conference League in the past 5 seasons. Example values: Real Madrid ~170,
Arsenal ~90, Inter ~75.

**Coverage gap — why it can't drive map ordering:**

| Tier | Clubs with a coefficient | Clubs without |
|---|---|---|
| Premier League | ~12–14 | ~6–8 |
| Serie A | ~8–10 | ~10–12 |
| Bundesliga / La Liga / Ligue 1 | ~6–8 each | majority |
| Serie B | 0 | all 20 |
| Serie C | 0 | all ~60 |

Using a NULL-heavy field for z-index or badge ordering creates an inconsistent map.
`average_attendance` (already in DB, populated for all teams) is used instead as the
within-tier tiebreaker.

**Where it IS useful — team detail page:**
Showing "UEFA coefficient: 89.0" on Arsenal's detail page is informative and the NULL
case (Serie B / C clubs) simply renders nothing — no broken experience.

**What the follow-on task involves:**
- `Team.uefa_coefficient = models.FloatField(null=True, blank=True)` — one migration
- Management command `update_club_coefficients` — scrapes
  `https://en.wikipedia.org/wiki/UEFA_coefficient#Club_coefficients` (same source,
  same `requests` + `bs4` pattern as `update_uefa_ranking`)
- Display on `team_detail.html`: one extra `{% if team.uefa_coefficient %}` line
- No map.js changes

**Estimated effort:** half a day. Defer until after Sprint 3 is merged.

---

## Rollback plan

```bash
# Revert model: reverse migration
python manage.py migrate italiastadiaapp <previous_migration>

# Revert JS/CSS/templates
git checkout main -- italiastadiaapp/static/js/map.js
git checkout main -- italiastadiaapp/static/css/styles.css
git checkout main -- italiastadiaapp/templates/index.html
git checkout main -- italiastadiaapp/views.py
```
