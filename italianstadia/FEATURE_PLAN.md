# Feature Plan — 3D Building Explorer Map on Stadium Detail Page
_Created: 2026-06-10 | Branch: feature/3d-building-explorer_

## Problem / Goal
The stadium detail page has a satellite mini-map with an animated fly-in, but it is read-only — the user cannot freely explore the stadium's 3D shape. We want to add a second, interactive 3D map card below the stats section that uses OpenFreeMap vector tiles with OSM building extrusions, letting the user orbit, zoom and tilt the stadium structure at will. The existing satellite map stays unchanged.

## Scope
**In scope:**
- [x] `stadium-detail-map.js` — extract shared `buildLogoMarker()` helper, add second MapLibre instance with OpenFreeMap vector tiles + `fill-extrusion` building layer + reset button
- [ ] `stadium_detail.html` — insert full-width 3D Explorer card between stats row and teams section
- [ ] `styles.css` — add `#stadium-3d-map` height rule

**Out of scope (do not touch):**
- The satellite map animation, replay button, or its data attributes
- `views.py` — no model or context changes (reuses `team_logos_json` already in context)
- Any map on the main Leaflet index page
- Sprint 5 / Sprint 6 work

## Design decisions
1. **Tile source: OpenFreeMap** | Alt: MapTiler/Mapbox | Reason: No API key, free, OpenMapTiles schema, building height data for all major European stadiums.
2. **Layout: full-width card below stats** | Alt: tab switcher / side-by-side | Reason: Works on all screen sizes; satellite stays in context; 3D gets enough height to be dramatic.
3. **Pitch 60° on load** | Alt: start flat | Reason: Buildings visible immediately, no gesture needed.
4. **Height-based colour ramp (light→navy blue)** | Alt: uniform colour | Reason: Taller stadium structure naturally pops brighter than low surroundings.
5. **Auto-detect vector source name** | Alt: hardcode `"openmaptiles"` | Reason: Future-proof if OpenFreeMap renames their source.

## Files that will change
| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/static/js/stadium-detail-map.js` | Edit | Extract `buildLogoMarker()`, add 3D map init + building layer + reset button |
| `italiastadiaapp/templates/stadium_detail.html` | Edit | Insert 3D Explorer card HTML |
| `italiastadiaapp/static/css/styles.css` | Edit | Add `#stadium-3d-map { height: 480px }` rule |

## Implementation steps
1. [x] `stadium-detail-map.js` — refactor to shared helper + add 3D map section
2. [ ] `stadium_detail.html` — insert 3D Explorer card HTML between stats row and teams section
3. [ ] `styles.css` — add `#stadium-3d-map` height rule
4. [ ] Manual test on San Siro / Benfica / Allianz Arena

## PostgreSQL safety check
_No model changes — N/A._

## Test plan
- Satellite map: animation fires on scroll, replay button works, logo(s) show ✓
- 3D map: buildings visible at pitch 60°, drag rotates bearing, scroll zooms
- Reset button: map smoothly returns to zoom 16 / pitch 60° / bearing -20°
- Multi-tenant (Meazza): split badge on BOTH maps
- No coordinates: neither map card renders (`has_coords` guard works)

## Rollback plan
Frontend-only changes. Revert `stadium-detail-map.js`, delete the 3D card block from the template, remove the `#stadium-3d-map` CSS rule.

---

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

---

# Feature Plan — Sprint 4: Mobile UI, Live Search, Marker Clustering, Club Coefficients
_Created: 2026-06-09 | Branch: feature/sprint-4_

## Problem / Goal

Four enhancements to improve usability and data depth:

1. **Mobile-first UI**: The navbar filter row overflows awkwardly on phones. On ≤768px the filter controls should collapse behind a "Filters" toggle button that opens a full-width slide-up drawer. The map should fill the full viewport height. Leaflet popups should anchor as a bottom sheet rather than a floating callout.
2. **Live search**: There is no way to jump directly to a team or stadium by name; users must know which country/league to filter first. A search box should let users type any name and fly the map to the matching marker.
3. **Marker clustering**: At low zoom levels the European map shows 400+ overlapping badges. A cluster layer should collapse nearby markers into a count bubble at zoom ≤5.
4. **UEFA club coefficients** (explicitly deferred from Sprint 3): `Team.uefa_coefficient` field, `update_club_coefficients` management command, and display on the team detail page.

Success: on a 375 px phone the map fills the screen; tapping "Filters" slides up a drawer with all controls; typing "Arsenal" in the search box flies the map to the Emirates and opens its popup; zooming out to level 3 shows count bubbles; Arsenal's team detail page shows "UEFA coefficient: 87.5".

---

## Scope

**In scope:**
- [x] WS1 — Mobile drawer: `#filterToggleBtn` in navbar; `#filterDrawer` wrapping the filter row; slides up on mobile; map fills full viewport height (`100dvh`); Leaflet popup → bottom sheet on ≤768px
- [x] WS2 — Live search input in the filter area; results dropdown (max 5 entries); fly-to + open popup on selection; searches `marker.stadiumName` and `marker.primaryTeam.name` / all `marker.teams[*].name`
- [x] WS3 — Leaflet.markercluster CDN; `L.markerClusterGroup` replacing direct `map.addLayer` calls in `applyFilters()`; `disableClusteringAtZoom: 6`
- [x] WS4 — `Team.uefa_coefficient FloatField`; migration; `update_club_coefficients` management command; `{% if team.uefa_coefficient %}` block in `team_detail.html`
- [x] WS5 — Back navigation: `team_list.html` appends `?from_list=<country>` to team links; `team_detail` view reads it; `team_detail.html` renders "← Back to team list (Country)" when present, plain "← Back to teams" otherwise
- [x] WS6 — CLP: fix tap dead zones on touch devices (add fallback `countryRow.click`); replace `window.innerWidth` hover guard with `matchMedia("(hover: hover)")`; stronger `.active` CSS (left-border accent); visible-select highlight class `filter-has-value`
- [x] WS7 — Map ordering: asymmetric zoom padding `paddingTopLeft:[30,110]` / `paddingBottomRight:[30,40]` across all `fitBounds` calls
- [x] WS8 — Team list: `leagues_qs` ordered by `country__uefa_rank`; flag emoji helper in views.py; `{% regroup %}` in template creates country dropdown navbar with flags
- [x] WS9 — Unknown ownership: extract `classify_ownership()` + `PUBLIC_KEYWORDS` to `italiastadiaapp/ownership.py`; new `fix_unknown_ownership` management command
- [ ] WS10 — Multi-tenant stadium logos: split-circle badge marker when a stadium has 2+ tenants (e.g. Meazza showing Inter + AC Milan side-by-side); popup redesigned to show all tenant team logos simultaneously in a horizontal logo strip (replacing ← / → one-at-a-time navigation)

**Out of scope (do not touch):**
- Development mode marker clustering (circles stay as direct `map.addLayer`)
- `stadium-detail-map.js`
- Any scraper / JSON data file changes
- Server-side search endpoint (client-side over already-loaded GeoJSON is sufficient)
- `average_attendance` ranking on map markers — not changing z-index / ordering logic

---

## Design decisions

1. **Mobile drawer: wrap existing filter row, don't move DOM nodes.**
   Option A (rejected): hide the filter row on mobile; clone nodes into a separate drawer div. Breaks: sessionStorage restore reads element IDs that must be in a single DOM location; cloning duplicates IDs.
   Option B (chosen): add `id="filterDrawer"` to the existing `<div class="d-flex … w-100">` filter row. On desktop, `#filterDrawer` is `display: flex` (inline, as today). On ≤768px, `#filterDrawer` is `display: none` by default; a toggle button shows it as a `position: fixed` bottom panel. One set of IDs, zero sessionStorage impact, zero JS structural changes to applyFilters().

2. **Live search: client-side over `operationalMarkers` array.**
   All GeoJSON is loaded once at page load. Searching `operationalMarkers` (~400 entries) in-memory is instant. A server-side endpoint adds a Django view + URL + JS round-trip for zero benefit at current data size. Re-evaluate when stadiums exceed ~5000.

3. **Search matches stadium name AND all team names at a marker.**
   `marker.stadiumName` (set at map.js:1030) and every `marker.teams[i].name` (set at map.js:1009) are searched. Multi-tenant stadiums (e.g. Olimpico, shared by Roma and Lazio) return a single result regardless of which team name was typed.

4. **Search lives inside the filter row / drawer.**
   On desktop it sits at the start of the second navbar row. On mobile it is inside the drawer — the user opens the drawer to search. Alternative: keep search always-visible in the top navbar row on mobile. Rejected: the top row is already tight (brand + mode switch); the extra input would force wrapping or tiny font sizes. Acceptable trade-off: search-heavy users on mobile use the drawer.

5. **Cluster group: `disableClusteringAtZoom: 6`.**
   At zoom ≥6 (city level) individual club badges appear; below 6, clusters. At Europe zoom (3–5), city clusters are clean count bubbles. `maxClusterRadius: 60` keeps city-level clusters from merging stadiums that are geographically separate.
   Alternative: threshold at 5. Rejected: at zoom 5 many country capitals already show 2–4 clubs within cluster radius — individual badges are more useful there.

6. **Cluster group operational-only.**
   Development markers (< 100 records, always low density) keep direct `map.addLayer`. Avoids adding cluster state to the development mode path.

7. **`applyFilters()` rebuild strategy with cluster group.**
   Current `applyFilters()` calls `map.removeLayer(marker)` / `marker.addTo(map)` per marker. With the cluster group, replace all those calls with `clusterGroup.clearLayers()` at the top of `applyFilters()`, then rebuild with `clusterGroup.addLayer(marker)` for each visible marker. Simpler than per-marker add/remove on the cluster group, and avoids stale layer state.

8. **UEFA coefficient source: Wikipedia, same page as `update_uefa_ranking`.**
   `https://en.wikipedia.org/wiki/UEFA_coefficient` already has a "Club coefficients" section. Same `requests` + `bs4` pattern, no new dependency. Match Wikipedia club names to `Team.name` case-insensitively; log `WARNING` for unmatched rows. Coefficient is shown on team_detail only when non-null (Sprint 3 deferred section describes the use-case in detail).

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/models.py` | Edit | Add `Team.uefa_coefficient` FloatField |
| `italiastadiaapp/migrations/` | New | Migration for `Team.uefa_coefficient` |
| `italiastadiaapp/management/commands/update_club_coefficients.py` | New | Scrape + save club coefficients |
| `italiastadiaapp/templates/team_detail.html` | Edit | Display coefficient when non-null |
| `italiastadiaapp/templates/index.html` | Edit | Add `#filterToggleBtn`, `id="filterDrawer"`, search input markup, markercluster CDN links |
| `italiastadiaapp/templates/team_list.html` | Edit | Append `?from_list=…` to each "View team" link; grouped country dropdown navbar with flags |
| `italiastadiaapp/views.py` | Edit | `team_detail`: `from_list` param; `team_list`: order by `uefa_rank`, add `flag` to sections; `_country_flag_emoji()` helper |
| `italiastadiaapp/templates/team_detail.html` | Edit | Conditional back-link in `{% block extra_nav %}` |
| `italiastadiaapp/static/css/styles.css` | Edit | Stronger CLP `.active` styles; `select.filter-has-value` highlight |
| `italiastadiaapp/static/js/map.js` | Edit | CLP fallback click handler; `matchMedia` hover guard; `data-rank` on options; CLP order from DOM; asymmetric zoom padding; `countryFlagEmoji()`; `country_code` in league objects |
| `italiastadiaapp/ownership.py` | New | Extracted `classify_ownership()` + `PUBLIC_KEYWORDS` |
| `italiastadiaapp/management/commands/fix_unknown_ownership.py` | New | Re-classify UNKNOWN stadiums with `owner_raw` set |
| `italiastadiaapp/static/css/styles.css` | Edit | Mobile drawer, bottom-sheet popup, search dropdown styles |
| `italiastadiaapp/static/js/map.js` | Edit | `clusterGroup` init, `applyFilters()` cluster calls, live search logic, drawer toggle |

---

## Implementation steps

Steps are ordered bottom-up (model → backend → frontend). Complete each workstream in sequence.

### WS4 — UEFA club coefficients

1. [ ] **Model** — in `italiastadiaapp/models.py`, add to `Team`:
   ```python
   uefa_coefficient = models.FloatField(null=True, blank=True)
   ```

2. [ ] **Migration** — run `python manage.py makemigrations && python manage.py migrate`.
   Safe: nullable float, existing rows get NULL automatically.

3. [ ] **Management command** — create `italiastadiaapp/management/commands/update_club_coefficients.py`:
   ```python
   from django.core.management.base import BaseCommand
   import requests
   from bs4 import BeautifulSoup
   from italiastadiaapp.models import Team

   class Command(BaseCommand):
       help = "Fetch UEFA 5-year club coefficients from Wikipedia and update Team.uefa_coefficient"

       def handle(self, *args, **options):
           url = "https://en.wikipedia.org/wiki/UEFA_coefficient"
           soup = BeautifulSoup(requests.get(url, timeout=15).text, "html.parser")
           # The "Club coefficients" section is the second wikitable on the page.
           # Parse rank, club name, coefficient (Points column).
           # For each row: Team.objects.filter(name__iexact=club_name).update(uefa_coefficient=value)
           # Log WARNING for unmatched rows.
   ```
   Usage: `python manage.py update_club_coefficients`

4. [ ] **team_detail.html** — add inside the existing stats/info section (find a `<dl>` or similar block):
   ```html
   {% if team.uefa_coefficient %}
   <dt>UEFA coefficient</dt>
   <dd>{{ team.uefa_coefficient|floatformat:1 }}</dd>
   {% endif %}
   ```

### WS3 — Marker clustering

5. [ ] **index.html** — add Leaflet.markercluster CDN links immediately after the existing Leaflet lines (before `styles.css`):
   ```html
   <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster/dist/MarkerCluster.css"/>
   <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster/dist/MarkerCluster.Default.css"/>
   ```
   And after the Leaflet JS `<script>` tag:
   ```html
   <script src="https://unpkg.com/leaflet.markercluster/dist/leaflet.markercluster.js"></script>
   ```

6. [ ] **map.js** — immediately after `const map = L.map(...)` is initialised (top of file), create the cluster group and add it to the map:
   ```js
   const clusterGroup = L.markerClusterGroup({
       maxClusterRadius: 60,
       disableClusteringAtZoom: 6,
       chunkedLoading: true,
   });
   map.addLayer(clusterGroup);
   ```

7. [ ] **map.js — `applyFilters()`** — at the very start of the function, replace the per-marker removal loop with a single clear:
   ```js
   clusterGroup.clearLayers();   // ← replaces the forEach map.removeLayer loop
   ```
   Then for each visible marker replace `marker.addTo(map)` → `clusterGroup.addLayer(marker)`.
   Remove the `map.removeLayer(marker)` calls inside the loop (clearLayers already handled them).

8. [ ] **map.js — initial load** — the final `marker.addTo(map)` at map.js:1066 (where each marker is first placed) should also become `clusterGroup.addLayer(marker)`. This ensures the initial render goes through the cluster group.

9. [ ] **Smoke test**: zoom to 3 — verify count bubbles appear. Click a bubble — verify it zooms and splits. Zoom to 7 — verify individual badges appear.

### WS2 — Live search

10. [ ] **index.html** — add the search input at the very start of the `#filterDrawer` div (before `#operationalFilters`):
    ```html
    <div id="searchWrap" class="search-wrap">
        <input type="search" id="liveSearch" class="form-control form-control-sm"
               placeholder="Search team or stadium…" autocomplete="off">
        <ul id="searchResults" class="search-results" style="display:none"></ul>
    </div>
    ```

11. [ ] **styles.css** — add search component styles (outside any @media block, so they apply on all sizes):
    ```css
    .search-wrap {
        position: relative;
        flex-shrink: 0;
        width: clamp(160px, 18vw, 300px);
    }
    .search-results {
        position: absolute;
        top: 100%;
        left: 0;
        right: 0;
        z-index: 9999;
        background: #1a1a1a;
        border: 1px solid #555;
        border-top: none;
        border-radius: 0 0 6px 6px;
        list-style: none;
        padding: 0;
        margin: 0;
        max-height: 220px;
        overflow-y: auto;
    }
    .search-results li {
        padding: 8px 12px;
        color: #ddd;
        cursor: pointer;
        font-size: 13px;
    }
    .search-results li:hover { background: #333; }
    ```
    Inside the `@media (max-width: 768px)` block: `.search-wrap { width: 100%; }`.

12. [ ] **map.js** — after the `operationalMarkers.push(marker)` call (end of the GeoJSON fetch `.then` block), wire up live search. Add after `populateCountryFilter()` is called:
    ```js
    wireSearch();
    ```
    Add the `wireSearch()` function near the top of the JS module (alongside other utility functions):
    ```js
    function wireSearch() {
        const input   = document.getElementById("liveSearch");
        const results = document.getElementById("searchResults");
        if (!input) return;
        let debounce;

        input.addEventListener("input", () => {
            clearTimeout(debounce);
            debounce = setTimeout(() => {
                const q = input.value.trim().toLowerCase();
                results.innerHTML = "";
                if (q.length < 2) { results.style.display = "none"; return; }

                const hits = operationalMarkers.filter(m => {
                    if (m.stadiumName?.toLowerCase().includes(q)) return true;
                    return (m.teams || []).some(t => t.name?.toLowerCase().includes(q));
                }).slice(0, 5);

                if (!hits.length) { results.style.display = "none"; return; }

                hits.forEach(m => {
                    const label = m.primaryTeam?.name
                        ? `${m.primaryTeam.name} — ${m.stadiumName}`
                        : m.stadiumName;
                    const li = document.createElement("li");
                    li.textContent = label;
                    li.addEventListener("click", () => {
                        map.flyTo(m.getLatLng(), 12, { duration: 1.2 });
                        setTimeout(() => m.openPopup(), 1300);
                        input.value = "";
                        results.style.display = "none";
                    });
                    results.appendChild(li);
                });
                results.style.display = "block";
            }, 250);
        });

        document.addEventListener("click", e => {
            if (!e.target.closest("#searchWrap")) results.style.display = "none";
        });
    }
    ```

13. [ ] Confirm `m.openPopup()` works on a badge marker — it's an `L.marker`, so `.openPopup()` opens the bound popup if any. Since popups are created on click (not pre-bound via `marker.bindPopup()`), calling `m.openPopup()` directly won't work. Instead, simulate a programmatic click: `m.fire("click")`. Update step 12 accordingly:
    ```js
    // Replace: setTimeout(() => m.openPopup(), 1300);
    // With:
    setTimeout(() => m.fire("click"), 1300);
    ```

### WS5 — Team list back navigation & filter persistence

18. [ ] **team_list.html** — append `?from_list={{ selected_country|urlencode }}` to each team card link (line 114). The parameter is an empty string when "All countries" is selected — that is fine, the view handles it:
    ```html
    <a href="{% url 'italiastadiaapp:team_detail' team.pk %}?from_list={{ selected_country|urlencode }}"
       class="btn btn-sm btn-outline-secondary">View team</a>
    ```
    This passes the active country filter through to the detail page without any JS.

19. [ ] **views.py — `team_detail`** — read the `from_list` param and pass context vars. Find the `team_detail` view function and add after the `team = get_object_or_404(...)` line:
    ```python
    from_list   = request.GET.get("from_list", None)   # None = not from list; "" = all countries
    back_country = from_list if from_list else ""
    context = {
        "team": team,
        "from_list": from_list is not None,    # True iff we came from the team list
        "back_country": back_country,
    }
    ```

20. [ ] **team_detail.html — `{% block extra_nav %}`** — use the context vars to render the appropriate back link:
    ```html
    {% block extra_nav %}
    {% if from_list %}
        <a href="{% url 'italiastadiaapp:team_list' %}{% if back_country %}?country={{ back_country }}{% endif %}"
           class="btn btn-sm btn-outline-light ms-auto">
            ← Back to team list{% if back_country %} ({{ back_country }}){% endif %}
        </a>
    {% else %}
        <a href="{% url 'italiastadiaapp:team_list' %}" class="btn btn-sm btn-outline-light ms-auto">
            ← Back to teams
        </a>
    {% endif %}
    {% endblock %}
    ```
    When the user navigates from map popup → team_detail (no `from_list` param), they see the plain "← Back to teams" link. When they navigate from a filtered team list, they see "← Back to team list (England)" and land on the same filtered view.

---

### WS1 — Mobile-first UI

14. [ ] **index.html** — three changes:
    a. Add `id="filterDrawer"` to the existing `<div class="d-flex align-items-center flex-wrap gap-2 pb-1 w-100">` filter row. Keep all child elements unchanged.
    b. Add `<button id="filterToggleBtn">` to the first row of the navbar, between the mode-switch and the `<div class="w-100">` flex break:
       ```html
       <button id="filterToggleBtn" class="btn btn-sm btn-outline-light" style="display:none;">
           ☰ Filters
       </button>
       ```
    c. On mobile the search input (added in step 10) is already inside `#filterDrawer`, so no extra placement needed.

15. [ ] **styles.css — mobile section** — add inside / extend the `@media (max-width: 768px)` block:
    ```css
    @media (max-width: 768px) {
        /* Show filter toggle button */
        #filterToggleBtn { display: inline-flex !important; }

        /* Hide the filter row by default; it becomes a fixed drawer */
        #filterDrawer {
            display: none;
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: #212529;
            padding: 16px 16px 24px;   /* extra bottom padding for home-bar */
            z-index: 10000;
            border-top: 2px solid #444;
            border-radius: 16px 16px 0 0;
            max-height: 72vh;
            overflow-y: auto;
            flex-direction: column;
            gap: 10px;
        }
        #filterDrawer.open { display: flex; }

        /* Map fills full viewport height on mobile */
        #map {
            height: 100dvh;
            margin-top: 0;
        }

        /* Leaflet popup → bottom sheet */
        .leaflet-popup {
            position: fixed !important;
            bottom: 0 !important;
            left: 0 !important;
            right: 0 !important;
            top: auto !important;
            margin: 0 !important;
            transform: none !important;
        }
        .leaflet-popup-tip-container { display: none; }
        .leaflet-popup-content-wrapper {
            border-radius: 16px 16px 0 0;
            width: 100% !important;
            max-height: 55vh;
            overflow-y: auto;
            box-shadow: 0 -4px 24px rgba(0,0,0,0.6);
        }
        .leaflet-popup-close-button {
            top: 12px !important;
            right: 12px !important;
        }
    }
    ```

16. [ ] **map.js** — add drawer toggle logic (can be placed near the CLP picker open/close block):
    ```js
    const filterToggleBtn = document.getElementById("filterToggleBtn");
    const filterDrawer    = document.getElementById("filterDrawer");
    if (filterToggleBtn && filterDrawer) {
        filterToggleBtn.addEventListener("click", e => {
            e.stopPropagation();
            filterDrawer.classList.toggle("open");
            filterToggleBtn.textContent = filterDrawer.classList.contains("open")
                ? "✕ Close"
                : "☰ Filters";
        });
        // Tapping the map closes the drawer
        map.on("click", () => {
            filterDrawer.classList.remove("open");
            filterToggleBtn.textContent = "☰ Filters";
        });
    }
    ```

17. [ ] **Smoke test on Chrome DevTools — iPhone SE (375 × 667)**:
    - Map fills screen; first navbar row shows brand + mode switch + "☰ Filters" button
    - Filter row (second navbar row) is hidden
    - Tap "☰ Filters" → drawer slides up from bottom with search input + all filter controls
    - Apply a country filter inside drawer → map updates, drawer stays open
    - Tap a badge marker → popup anchors to screen bottom (not at marker position)
    - Tap map → drawer closes
    - Rotate to landscape → drawer and bottom-sheet popup still usable

---

### WS6 — CLP responsiveness fix + filter active-state highlighting

21. [ ] **map.js — CLP click handling**: The `countryRow` container has no click handler — only the child `nameSpan` and `chevron` do. On touch devices, tapping between or slightly outside them hits the container div and nothing fires. Fix: add a click handler directly on `countryRow` that applies the country filter, duplicating the `nameSpan` handler as a fallback:
    ```js
    // After the existing nameSpan and chevron listeners are attached:
    countryRow.addEventListener("click", function (e) {
        // Only fire if neither the nameSpan nor chevron handled it
        // (they stopPropagation — if we reach here it's a gap tap)
        countryFilter.value = country;
        leagueFilter.value  = "";
        countryFilter.dispatchEvent(new Event("change"));
        updatePickerLabel();
        closePicker();
    });
    ```
    Keep `e.stopPropagation()` on both `nameSpan` and `chevron` handlers so the `countryRow` fallback only fires for gap taps.

22. [ ] **map.js — CLP mobile: disable mouseenter auto-expand on touch**. Currently `mouseenter` auto-expands the accordion on desktop (width > 768). On some tablets/hybrids, `mouseenter` fires on first touch, opening the accordion; the user must tap again to actually select. Tighten the guard: use `window.matchMedia("(hover: hover)")` instead of `window.innerWidth > 768`:
    ```js
    countryRow.addEventListener("mouseenter", function () {
        if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
            // genuine mouse hover — expand accordion
            ...
        }
    });
    ```

23. [ ] **styles.css — stronger active-state visual for CLP rows**. Replace the current `.clp-league-row.active` (font-weight only) and `.clp-country-row.active` (faint background) with a more visible indicator:
    ```css
    .clp-country-row.active {
        background: rgba(100, 160, 255, 0.18);
        color: #fff;
        border-left: 3px solid #4a9eff;
    }
    .clp-league-row.active {
        background: rgba(100, 160, 255, 0.14);
        color: #fff;
        font-weight: 700;
        border-left: 3px solid #4a9eff;
        padding-left: 27px;   /* compensate for 3px border */
    }
    /* Also tighten hover vs. active distinction */
    .clp-country-row:hover:not(.active) {
        background: rgba(255, 255, 255, 0.07);
    }
    ```

24. [ ] **map.js + styles.css — active-state highlight on visible filter selects**. The `ownershipFilter` and `stadiumFilter` selects have no visual indicator when a non-default value is selected. Add a JS function that adds/removes a CSS class and call it after every filter change:
    ```js
    function updateSelectHighlights() {
        [ownershipFilter, stadiumFilter].forEach(sel => {
            sel.classList.toggle("filter-has-value", sel.value !== "");
        });
    }
    ```
    Call `updateSelectHighlights()` inside `updateClearButton()` (which is already called after every filter change).
    In `styles.css`:
    ```css
    select.filter-has-value {
        border-color: #4a9eff !important;
        box-shadow: 0 0 0 2px rgba(74, 158, 255, 0.25);
        color: #fff;
    }
    ```

---

### WS7 — Map country ordering fix + zoom padding

25. [ ] **views.py — expose `country_rank` reliably in GeoJSON**. Verify `stadiums_geojson` already returns `country_rank` for every team (it does, via `t.league.country.uefa_rank`). Ensure `update_uefa_ranking` is run against all 55 UEFA member countries so NULLs don't exist. Add a note to `CLAUDE.md`: _"Run `update_uefa_ranking` whenever a new Country is added so `countryRankMap` in map.js is complete."_

26. [ ] **map.js — `populateCountryFilter()`: add `data-rank` attribute to each `<option>` so the JS sort can use it even if `countryRankMap` is incomplete at call time**:
    ```js
    function populateCountryFilter() {
        const countries = [...new Set(
            markers.flatMap(m => m.leagues.map(l => l.country)).filter(Boolean)
        )].sort((a, b) => (countryRankMap[a] ?? 999) - (countryRankMap[b] ?? 999));
        countryFilter.innerHTML = `<option value="">All countries</option>`;
        countries.forEach(c => {
            const opt = document.createElement("option");
            opt.value = c;
            opt.textContent = c;
            opt.dataset.rank = countryRankMap[c] ?? 999;  // ← new: written to DOM
            countryFilter.appendChild(opt);
        });
        buildPickerUI();
    }
    ```
    In `buildPickerUI()`, derive the sort order from the `countryFilter.options` array directly (already in order) instead of re-sorting from `countryRankMap`:
    ```js
    // Replace the existing sort block in buildPickerUI():
    const orderedCountries = [...countryFilter.options]
        .filter(o => o.value !== "")
        .map(o => o.value);
    // Then iterate orderedCountries instead of the manually-sorted set
    ```
    This guarantees the CLP panel order exactly matches the hidden select order.

27. [ ] **map.js — `fitToVisibleMarkers()`: fix navbar clip by using asymmetric padding**. Replace the single `padding: [20, 20]` call:
    ```js
    function fitToVisibleMarkers(visibleMarkers) {
        if (!visibleMarkers || visibleMarkers.length === 0) {
            const fallback = allMarkersBounds || EUROPE_FOOTBALL_BOUNDS;
            map.fitBounds(fallback, { paddingTopLeft: [30, 110], paddingBottomRight: [30, 30], animate: true });
            return;
        }
        const group = L.featureGroup(visibleMarkers);
        map.fitBounds(group.getBounds(), {
            paddingTopLeft:     [30, 110],   // [left, top] — 110px clears the fixed navbar
            paddingBottomRight: [30, 40],    // generous bottom for mobile home bar
            maxZoom: 12,
            animate: true
        });
    }
    ```
    Also update the two `fitBounds` calls in `zoomToCountry()` fallback path and in `clearFiltersBtn` handler to use the same asymmetric padding.

---

### WS8 — Team list: UEFA ordering + navbar flags + league hierarchy

28. [ ] **views.py — `team_list`: order by `country__uefa_rank`, not `country__name`**. Change line 269–271:
    ```python
    # Before:
    leagues_qs = League.objects.select_related("country").order_by(
        "country__name", "division_level"
    )
    # After:
    leagues_qs = League.objects.select_related("country").order_by(
        "country__uefa_rank", "country__name", "division_level"
    )
    ```
    `country__name` as secondary sort handles ties and NULL ranks gracefully (same pattern as `_available_countries()`).

29. [ ] **views.py — `team_list`: pass country flag to template context**. Add a helper function:
    ```python
    def _country_flag_emoji(code: str) -> str:
        """Convert ISO-2 country code to flag emoji. Handles GB→England special case."""
        OVERRIDES = {"GB": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"}   # England flag, not UK flag
        if code in OVERRIDES:
            return OVERRIDES[code]
        if len(code) == 2:
            return chr(0x1F1E0 + ord(code[0].upper()) - 65) + chr(0x1F1E0 + ord(code[1].upper()) - 65)
        return ""
    ```
    In `team_list`, add `flag` to each section:
    ```python
    sections.append({
        "league": league,
        "league_label": league.name,
        "anchor": f"league-{league.id}",
        "teams": section_teams,
        "flag": _country_flag_emoji(league.country.code) if league.country else "",
    })
    ```

30. [ ] **team_list.html — grouped navbar with flags + division submenu**. Replace the flat league button row with a Bootstrap dropdown grouped by country. Each country with multiple leagues gets a single dropdown:
    ```html
    <!-- Build a country→leagues map in the template -->
    {% regroup sections by league.country.name as country_sections %}
    {% for country_group in country_sections %}
        {% if country_group.list|length == 1 %}
            <!-- Single league: plain link with flag -->
            <a href="#{{ country_group.list.0.anchor }}"
               class="btn btn-outline-primary btn-sm">
                {{ country_group.list.0.flag }} {{ country_group.list.0.league_label }}
                ({{ country_group.list.0.teams|length }})
            </a>
        {% else %}
            <!-- Multiple leagues: Bootstrap dropdown -->
            <div class="dropdown d-inline-block">
                <button class="btn btn-outline-primary btn-sm dropdown-toggle"
                        data-bs-toggle="dropdown">
                    {{ country_group.list.0.flag }} {{ country_group.grouper }}
                </button>
                <ul class="dropdown-menu">
                    {% for section in country_group.list %}
                    <li>
                        <a class="dropdown-item" href="#{{ section.anchor }}">
                            {{ section.league_label }} ({{ section.teams|length }})
                        </a>
                    </li>
                    {% endfor %}
                </ul>
            </div>
        {% endif %}
    {% endfor %}
    ```
    Requires Bootstrap JS bundle (already loaded on all pages). This groups Italy into one "🇮🇹 Italy" dropdown listing [Serie A, Serie B, Serie C], England into "🏴󠁧󠁢󠁥󠁮󠁧󠁿 England" → [Premier League, Championship, League One]. Countries with only one league (most of them) show as a plain link.

31. [ ] **CLP panel — add flag emoji to country rows**. In `buildPickerUI()`, when building each `nameSpan`, prepend the flag. Need to pass flag data through the GeoJSON or derive it client-side. Since the GeoJSON already has `country` name and the markers have `marker.leagues[].country`, add a `country_code` to the GeoJSON team properties:
    - **views.py**: add `"country_code": t.league.country.code if t.league and t.league.country else ""` to each team dict in `stadiums_geojson`
    - **map.js**: in the marker-building loop, capture `country_code` per league: `code: t.country_code || ""`
    - **map.js — `buildPickerUI()`**: derive emoji from code client-side:
    ```js
    function countryFlagEmoji(code) {
        const overrides = { "GB": "🏴󠁧󠁢󠁥󠁮󠁧󠁿" };
        if (overrides[code]) return overrides[code];
        if (code.length === 2)
            return String.fromCodePoint(0x1F1E0 + code.charCodeAt(0) - 65)
                 + String.fromCodePoint(0x1F1E0 + code.charCodeAt(1) - 65);
        return "";
    }
    // In nameSpan construction:
    nameSpan.textContent = `${countryFlagEmoji(countryCode)} ${country}`;
    ```

---

### WS9 — Unknown ownership cleanup

32. [ ] **Refactor `classify_ownership()` to `italiastadiaapp/ownership.py`**. Currently the function and `PUBLIC_KEYWORDS` list live only in `scripts/populate_data_from_transfermrkt.py`. Extract them to a shared location so both the scraper and a management command can import it:
    - Create `italiastadiaapp/ownership.py` containing the `PUBLIC_KEYWORDS` list and `classify_ownership(owner_raw: str) -> str` function
    - Update `scripts/populate_data_from_transfermrkt.py` to import from `italiastadiaapp.ownership` (requires that the Django project root is on sys.path — it already is when called from the project root)

33. [ ] **Management command `fix_unknown_ownership`** — `italiastadiaapp/management/commands/fix_unknown_ownership.py`:
    ```python
    from django.core.management.base import BaseCommand
    from italiastadiaapp.models import Stadium
    from italiastadiaapp.ownership import classify_ownership

    class Command(BaseCommand):
        help = "Re-classify UNKNOWN ownership stadiums where owner_raw has a value"

        def add_arguments(self, parser):
            parser.add_argument("--dry-run", action="store_true",
                                help="Show what would change without writing to DB")

        def handle(self, *args, **options):
            dry_run = options["dry_run"]
            unknown_qs = Stadium.objects.filter(ownership="UNKNOWN").exclude(owner_raw="")
            self.stdout.write(f"Found {unknown_qs.count()} UNKNOWN stadiums with owner_raw set")
            changed = 0
            for s in unknown_qs:
                new_ownership = classify_ownership(s.owner_raw)
                if new_ownership == "UNKNOWN":
                    new_ownership = "PRIVATE"   # owner name present but no public keyword → private
                self.stdout.write(f"  {s.name}: '{s.owner_raw}' → {new_ownership}")
                if not dry_run:
                    s.ownership = new_ownership
                    s.save(update_fields=["ownership"])
                    changed += 1
            self.stdout.write(f"Updated {changed} stadiums.")
    ```
    Usage:
    - `python manage.py fix_unknown_ownership --dry-run` — preview changes
    - `python manage.py fix_unknown_ownership` — apply

34. [ ] **Run the command** after it's written:
    ```bash
    python manage.py fix_unknown_ownership --dry-run    # review
    python manage.py fix_unknown_ownership              # apply
    ```
    After running: `Stadium.objects.filter(ownership="UNKNOWN", owner_raw!="").count()` should be 0.

---

### WS10 — Multi-tenant stadium logos (split badge + logo strip popup)

**Problem:** Stadiums with multiple tenant clubs (e.g. Stadio Meazza = Inter Milan + AC Milan) only show a single logo on the map marker and cycle through teams one at a time via ← / → navigation in the popup. The user has no visual cue that the stadium is shared, and seeing both clubs at a glance is impossible.

**Goal:** When a stadium has 2+ tenants, the map badge shows a split circle with both logos side-by-side. The popup replaces the ← / → navigation with a horizontal logo strip at the top — all tenant logos are visible simultaneously; clicking a logo selects that team's info section below. No model, view, or URL changes are required — `props.teams[]` already contains all tenant data including `image_url`.

**Design decisions:**
1. **Split badge for exactly 2 tenants; "+N" overlay for 3+.** Splitting a circle into thirds or more is visually unreadable at 40 px. Show the top-2 tenants (sorted by `division_level` asc, i.e. highest tier first) and a `+N` mini-counter for any extras.
2. **No new `createBadgeIcon` API change.** Add a new `createMultiBadgeIcon(teams, sizePx)` function. When `teams.length === 1` it delegates to the existing `createBadgeIcon(teams[0].image_url, sizePx)` — zero regression risk.
3. **Logo strip replaces ← / → pagination.** The old navigation is opaque — users don't know how many teams exist. Logos are self-documenting and tappable on mobile. The active logo gets a coloured ring so the selected team is clear.
4. **Single-team popup gains a logo too.** Currently the popup is text-only. Adding the team logo improves visual identity and makes the single / multi cases feel consistent.

35. [ ] **CSS** — add to `italiastadiaapp/static/css/styles.css`:

    ```css
    /* ── Split badge for multi-tenant stadiums ─────────────────── */
    .badge-split {
        display: flex;
        overflow: hidden;   /* border-radius is set by .badge-icon-wrap */
    }
    .badge-split .badge-half {
        flex: 1;
        height: 100%;
        object-fit: cover;
        display: block;
    }
    .badge-split .badge-half-fallback {
        background: #9e9e9e;
        flex: 1;
    }
    .badge-split .badge-half:not(:last-child) {
        border-right: 1.5px solid rgba(255, 255, 255, 0.55);
    }
    /* "+N" mini-counter for 3+ tenants */
    .badge-extra-count {
        position: absolute;
        bottom: 2px;
        right: 2px;
        font-size: 8px;
        font-weight: 700;
        line-height: 14px;
        width: 14px;
        height: 14px;
        text-align: center;
        background: rgba(0, 0, 0, 0.75);
        color: #fff;
        border-radius: 50%;
        pointer-events: none;
    }

    /* ── Multi-tenant popup logo strip ─────────────────────────── */
    .popup-tenant-strip {
        display: flex;
        gap: 8px;
        justify-content: center;
        margin-bottom: 10px;
        padding-bottom: 8px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.15);
    }
    .popup-tenant-logo-btn {
        background: none;
        border: 2px solid transparent;
        border-radius: 50%;
        padding: 2px;
        cursor: pointer;
        transition: border-color 0.15s;
        flex-shrink: 0;
    }
    .popup-tenant-logo-btn.active,
    .popup-tenant-logo-btn:hover {
        border-color: #4fc3f7;
    }
    .popup-tenant-logo-btn img {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        object-fit: cover;
        display: block;
    }
    .popup-tenant-logo-btn .btn-logo-fallback {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        background: #555;
        display: block;
    }
    /* Team info panels — only the active one is shown */
    .popup-tenant-panel {
        display: none;
    }
    .popup-tenant-panel.active {
        display: block;
    }
    /* Single-team popup logo */
    .popup-single-logo {
        display: block;
        width: 40px;
        height: 40px;
        object-fit: contain;
        margin: 0 auto 6px;
    }
    ```

36. [ ] **`createMultiBadgeIcon(teams, sizePx)`** — add immediately below the existing `createBadgeIcon` function in `map.js`:

    ```js
    /**
     * Badge icon for multi-tenant stadiums (2+ teams sharing one ground).
     * - 1 team  → delegates to createBadgeIcon (backward compatible)
     * - 2 teams → split circle, left = team[0], right = team[1]
     * - 3+ teams → split circle of first two + "+N" mini-counter
     *
     * Teams are expected sorted highest-tier-first (lowest division_level first).
     */
    function createMultiBadgeIcon(teams, sizePx) {
        if (!teams || teams.length <= 1) {
            return createBadgeIcon(teams?.[0]?.image_url || null, sizePx);
        }
        const [t1, t2] = teams;
        const half1 = t1?.image_url
            ? `<img src="${t1.image_url}" alt="${t1.name}" class="badge-half">`
            : `<div class="badge-half badge-half-fallback"></div>`;
        const half2 = t2?.image_url
            ? `<img src="${t2.image_url}" alt="${t2.name}" class="badge-half">`
            : `<div class="badge-half badge-half-fallback"></div>`;
        const extra = teams.length > 2
            ? `<span class="badge-extra-count">+${teams.length - 2}</span>`
            : "";
        return L.divIcon({
            html: `<div class="badge-icon-wrap badge-sz-${sizePx} badge-active badge-split">${half1}${half2}${extra}</div>`,
            className: "",
            iconSize: [sizePx, sizePx],
            iconAnchor: [sizePx / 2, sizePx / 2],
            popupAnchor: [0, -sizePx / 2],
        });
    }
    ```

37. [ ] **Update marker creation** in `map.js` — the line that reads:
    ```js
    icon: createBadgeIcon(primaryTeam?.image_url || null, BADGE_SIZE.active),
    ```
    Change to:
    ```js
    icon: createMultiBadgeIcon(props.teams || [], BADGE_SIZE.active),
    ```
    _(The `props.teams` array is already sorted highest-tier-first by the GeoJSON endpoint, which orders by `division_level` ascending.)_

38. [ ] **Update icon-resize calls inside `applyFilters()`** — anywhere `createBadgeIcon` is called to resize a marker icon (active vs. inactive size), replace with `createMultiBadgeIcon(m.teams || [], size)`. The `m.teams` array is stored on the marker object at creation time (currently as `marker.teams`).

39. [ ] **Redesign `buildPopupContent(props, teamIndex = 0)`** for the multi-tenant case. When `teams.length > 1`, the popup renders:

    ```
    ┌───────────────────────────────────┐
    │  Stadio Giuseppe Meazza           │  ← stadium name
    │  Milan  |  Capacity: 75,923       │
    │  Ownership: PUBLIC                │
    │  ─────────────────────────────── │
    │   [Inter logo]  [AC Milan logo]   │  ← logo strip (WS10)
    │  ─────────────────────────────── │
    │  [active team info panel]         │  ← shows whichever logo is selected
    │    Name / League / View team      │
    │  ─────────────────────────────── │
    │  View stadium  |  Wikipedia        │
    └───────────────────────────────────┘
    ```

    Implementation sketch (add inside `buildPopupContent`):
    ```js
    if (teams.length > 1) {
        const logoStrip = teams.map((t, i) => `
            <button class="popup-tenant-logo-btn${i === teamIndex ? " active" : ""}"
                    data-team-idx="${i}" title="${t.name}">
                ${t.image_url
                    ? `<img src="${t.image_url}" alt="${t.name}">`
                    : `<span class="btn-logo-fallback"></span>`}
            </button>
        `).join("");

        const panels = teams.map((t, i) => `
            <div class="popup-tenant-panel${i === teamIndex ? " active" : ""}" data-team-idx="${i}">
                <strong>${t.name}</strong><br>
                <small>${t.league_name || t.tier_name || ""}</small><br>
                <a href="/team/${t.id}/" style="font-size:0.75rem">View team →</a>
            </div>
        `).join("");

        // ... assemble full popup HTML with strip + panels ...
    }
    ```

40. [ ] **Wire logo strip interaction** — in `attachPopupTeamNavigation()` (or inline in `buildPopupContent`), attach `click` handlers to each `.popup-tenant-logo-btn`:
    ```js
    popup.getElement()?.querySelectorAll(".popup-tenant-logo-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const idx = Number(btn.dataset.teamIdx);
            // Swap active classes on buttons
            btn.closest(".popup-tenant-strip")
               .querySelectorAll(".popup-tenant-logo-btn")
               .forEach(b => b.classList.toggle("active", b === btn));
            // Swap active class on panels
            btn.closest(".leaflet-popup-content")
               .querySelectorAll(".popup-tenant-panel")
               .forEach((p, i) => p.classList.toggle("active", i === idx));
        });
    });
    ```
    _(The existing ← / → `attachPopupTeamNavigation` logic can be retired once WS10 is live — keep it as a fallback under a guard `if teams.length > 1 && !stripPresent` during transition.)_

41. [ ] **Smoke test:** Open the map, find Stadio Meazza (Milan). Verify:
    - Badge marker shows two logos side-by-side in a split circle
    - Clicking the marker opens the popup with Inter + AC Milan logos in a horizontal strip
    - Clicking each logo swaps the team info section below (name, league, "View team")
    - The ← / → navigation buttons are gone from the popup

---

## PostgreSQL safety check

- [x] `Team.uefa_coefficient` is `FloatField(null=True, blank=True)` — safe nullable add, no default needed
- [x] No `SmallIntegerField` — float handles coefficient values (typically 0–200)
- [x] No scraped CharField length change
- [x] No new FK fields requiring `db_index`

---

## Test plan

**Automated:**
```bash
pytest italiastadiaapp/tests/ -v --tb=short    # all existing tests must pass
python manage.py makemigrations --check         # must exit 0 (no pending migrations)
python manage.py check                          # 0 issues
```

**New test** in `test_models.py`:
```python
def test_team_uefa_coefficient_field():
    from italiastadiaapp.models import Team
    import django.db.models as m
    field = Team._meta.get_field("uefa_coefficient")
    assert isinstance(field, m.FloatField)
    assert field.null is True
    assert field.blank is True
```

**Manual — clustering:**

| Action | Expected |
|--------|----------|
| Zoom to level 3 (Europe overview) | Overlapping badges collapse into count bubbles |
| Click a cluster bubble | Map zooms in, bubble splits into smaller clusters or badges |
| Zoom to level 7 | All individual badge markers visible, no clusters |
| Apply country filter, then zoom out | Only that country's clusters appear |

**Manual — live search:**

| Action | Expected |
|--------|----------|
| Type "Arsenal" (≥2 chars) | Dropdown shows "Arsenal — Emirates Stadium" |
| Click the result | Map flies to London at zoom 12; Emirates popup opens after ~1.3 s |
| Type "emi" | All teams/stadiums matching "emi" appear (max 5) |
| Type "xyz" | Dropdown hidden (no results) |
| Click anywhere outside search | Dropdown closes |
| Dev mode active, type "Arsenal" | Search still matches (searches `operationalMarkers`) |

**Manual — mobile drawer (Chrome DevTools iPhone SE 375 px):**

| Action | Expected |
|--------|----------|
| Page load | Map fills 100 dvh; navbar shows brand + mode switch + "☰ Filters" |
| Tap "☰ Filters" | Drawer slides up; button label → "✕ Close" |
| Apply ownership filter inside drawer | Marker count updates; drawer stays open |
| Tap badge marker | Bottom-sheet popup anchors to screen bottom |
| Tap map background | Drawer closes |
| Rotate to landscape | Drawer max-height 72 vh prevents overflow |

**Manual — CLP responsiveness & highlighting (WS6):**

| Action | Expected |
|--------|----------|
| On mobile (≤768px): tap between country name and chevron | Country filter applies (fallback handler fires) |
| On hybrid touch/mouse device: touch a country row | Accordion does NOT auto-expand on first touch (matchMedia guard) |
| Select "Italy → Serie A" | Country row has blue left-border + white text; Serie A row has blue left-border + bold white text |
| Open picker while "Italy" is selected | Italy row is visually highlighted; its leagues pre-expanded |
| Select a value in Ownership dropdown | Dropdown gets blue border highlight (`filter-has-value` class) |
| Clear filters | Ownership and Stadium dropdowns lose blue border |

**Manual — country ordering & zoom (WS7):**

| Action | Expected |
|--------|----------|
| Open CLP panel | England first, Italy second, Germany third (follows UEFA rank) |
| Run `python manage.py update_uefa_ranking` | All countries get a rank; re-open CLP — no countries stuck at the bottom alphabetically |
| Select "England" → zoom to England | All English stadiums visible; none clipped behind navbar at top |
| Select "Norway" (northern country with stadiums near top edge) | All stadiums visible with ≥110px top margin |
| On mobile, zoom to Italy | Bottom markers visible; not hidden behind home-bar area |

**Manual — team list order & navbar (WS8):**

| Action | Expected |
|--------|----------|
| Open `/teams/` | First section is the highest-UEFA-ranked country with scraped teams (England or Italy) |
| Navbar shows Italy (multi-league) | Single "🇮🇹 Italy" dropdown button; clicking opens [Serie A, Serie B, Serie C] |
| Navbar shows Norway (single league) | Single "🇳🇴 Eliteserien (N)" plain link |
| England dropdown | "🏴󠁧󠁢󠁥󠁮󠁧󠁿 England" with England flag (not 🇬🇧 UK flag) |
| CLP panel on map | "🇮🇹 Italy", "🏴󠁧󠁢󠁥󠁮󠁧󠁿 England" etc. next to each country name |

**Manual — unknown ownership (WS9):**

| Action | Expected |
|--------|----------|
| `python manage.py fix_unknown_ownership --dry-run` | Prints each UNKNOWN stadium + proposed new ownership; no DB write |
| Check proposed changes look correct | Stadiums with "City of…" or "Municipality" in owner_raw → PUBLIC; named clubs → PRIVATE |
| `python manage.py fix_unknown_ownership` | Updates DB; stdout shows count updated |
| After running: `Stadium.objects.filter(ownership="UNKNOWN").exclude(owner_raw="")` | Returns empty queryset |

**Manual — back navigation:**

| Action | Expected |
|--------|----------|
| Open team list, filter to "England", click "View team" on Arsenal | URL becomes `/team/42/?from_list=England` |
| On team detail: check back button | Shows "← Back to team list (England)" |
| Click back button | Lands on `/teams/?country=England` — filtered to England |
| Open team list with "All countries", click "View team" | URL has `?from_list=` (empty) |
| On team detail: check back button | Shows "← Back to team list" (no country suffix) |
| Click back button | Lands on `/teams/` — unfiltered |
| Navigate to team detail directly from map popup | Back button shows "← Back to teams" (no from_list param) |

**Manual — UEFA coefficient:**

| Action | Expected |
|--------|----------|
| `python manage.py update_club_coefficients` | Runs without error; logs INFO for matched teams |
| Visit Arsenal or Man City team detail page | "UEFA coefficient: 87.5" row visible |
| Visit a Serie B team detail page | No coefficient row shown (null suppressed by template guard) |

**Manual — multi-tenant stadium logos (WS10):**

| Action | Expected |
|--------|----------|
| Open map, zoom to Milan | Stadio Meazza badge shows a vertically split circle: left half = Inter Milan badge, right half = AC Milan badge |
| Click Meazza badge | Popup opens; two logos appear side-by-side in the header strip; no ← / → buttons |
| Click the Inter Milan logo in the strip | Inter logo gets a blue ring; info section below updates to Inter's name, league ("Serie A"), and "View team" link |
| Click the AC Milan logo in the strip | AC Milan logo gets the blue ring; info section updates accordingly |
| Open any single-tenant stadium popup | Popup shows that team's logo at the top; no strip, no navigation buttons |
| Stadium with 3 tenants (hypothetical) | Badge shows first two logos + "+1" overlay; popup strip shows all three logo buttons |
| Apply country/league filter that excludes Meazza | Meazza marker disappears normally (split badge has no effect on filter logic) |
| Resize browser window to 375 px (mobile) | Split badge, logo strip, and info panels all render correctly at small viewport width |

---

## Rollback plan

```bash
# WS4 model only:
python manage.py migrate italiastadiaapp <previous_migration_label>

# All frontend changes (JS + CSS + templates):
git checkout main -- italiastadiaapp/templates/index.html
git checkout main -- italiastadiaapp/static/css/styles.css
git checkout main -- italiastadiaapp/static/js/map.js
git checkout main -- italiastadiaapp/templates/team_detail.html

# WS10 only (no model changes — pure JS/CSS rollback):
git checkout main -- italiastadiaapp/static/js/map.js
git checkout main -- italiastadiaapp/static/css/styles.css
```
