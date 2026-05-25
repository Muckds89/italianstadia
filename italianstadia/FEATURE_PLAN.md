# Feature Plan — European leagues filter with country selector on main map
_Created: 2026-05-25 | Branch: feature/european-leagues-country-filter_

## Problem / Goal

The main map is Italy-only: the tier filter is hard-coded to "Serie A / Serie B /
Serie C" strings in the HTML and the JS `getMarkerColor()` encodes tier as an
integer. Adding European leagues requires a data model that can represent any
country + league, a GeoJSON contract that exposes that data, and a filter UI where
selecting a country replaces the league options with that country's actual leagues
(ordered by division level). The Italian tier/girone experience must continue to
work exactly as before.

Success: selecting "Italy" shows Serie A / Serie B / Serie C in the league dropdown;
selecting "England" shows Premier League / Championship / League One; picking a
league hides stadiums from other leagues; the Girone sub-filter still appears when
Serie C is active. All marker colours derive from `League.division_level`, not from
hardcoded tier integers.

## Scope

**In scope:**
- [ ] Add `Country` model (`name` CharField 255, `code` CharField 2)
- [ ] Add `League` model (`name` CharField 255, `country` FK, `division_level` IntegerField)
- [ ] Add `Team.league` FK (nullable, db_index, so existing rows are unaffected until
      the data migration runs)
- [ ] Schema migration (`makemigrations`)
- [ ] Data migration — creates Country(Italy, IT) + League(Serie A/B/C) rows and
      backfills `Team.league` from `Team.tier` for all existing Italian teams
- [ ] `admin.py` — register `Country` and `League` with sensible `list_display`
- [ ] `stadiums_geojson` — update `select_related` chain; add `country` to the feature
      properties; add `league_id`, `league_name`, `division_level` to each team entry
- [ ] `index.html` — replace hardcoded `<select id="tierFilter">` (and its 3 options)
      with `<select id="leagueFilter">` (empty; JS-populated); keep `gironeFilter`
- [ ] `map.js` — store `marker.country` and `marker.leagues` on each marker;
      implement `populateCountryFilter()` and `populateLeagueFilter(country)`;
      replace `selectedTier` with `selectedCountry + selectedLeague` in `applyFilters()`;
      update `gironeFilter` trigger to use league `division_level`; update
      `getMarkerColor()` to use `division_level`; make legend data-driven
- [ ] `test_api.py` — assert `country`, `league_id`, `division_level` in GeoJSON
- [ ] `test_models.py` — Country + League model tests
- [ ] Update GeoJSON contract in `CLAUDE.md`

**Out of scope (do not touch):**
- Scraping European data — separate `scraper/` task
- `TeamSeasonRecord` model — Phase 3
- `stadium_list.html`, `team_list.html` — still read `Team.tier`; leave them alone
- `Team.tier` field — keep it; it drives existing list views; the data migration sets
  both `tier` AND `league` so both work simultaneously
- `map.js` modularisation — still Phase 1 tech debt; documented below, out of scope

## Design decisions

1. **`League.division_level` not `tier`** | Alternative: reuse the name `tier` |
   Reason: `Team.tier` already means something specific (Italian 1/2/3). Using
   `division_level` on `League` avoids confusion — it's an ordering int within a
   country's pyramid, not a synonym for the existing field.

2. **Data migration to backfill Italian teams** | Alternative: leave `Team.league`
   null for Italy and derive it at query time from `Team.tier` |
   Reason: deriving at query time requires a JOIN-time lookup of which league ID
   corresponds to tier 1 for Italy — fragile and slow. A one-time data migration sets
   `Team.league` for all Italian rows once and keeps the query simple.

3. **`populateLeagueFilter(country)` reads from loaded GeoJSON, not a new endpoint** |
   Alternative: `GET /api/leagues/?country=X` |
   Reason: all marker data is already in memory. Collecting distinct leagues from
   `marker.leagues` is O(n) in JS with no round-trip. Avoids a new URL + view + test.

4. **`division_level` stored as `data-division-level` on `<option>` elements** |
   Alternative: JS Map keyed by league ID |
   Reason: the girone filter must trigger when division_level===3 AND country===Italy.
   Storing it on the `<option>` keeps the check as a single `selectedOption.dataset`
   read — no separate lookup structure needed.

5. **`getMarkerColor()` keyed on `division_level`, not league ID or name** |
   Alternative: per-country colour palettes |
   Reason: division 1 = green (top flight), division 2 = white, division 3 = red is
   universally readable regardless of country. Country-specific palettes can be added
   later; starting neutral avoids hard-coding England=red, Germany=black, etc.

6. **Legend becomes data-driven from the loaded GeoJSON** | Alternative: keep
   hardcoded strings |
   Reason: with dynamic leagues the hardcoded "Serie A / Serie B / Serie C" strings
   are wrong when a non-Italian country is selected. The legend must list the leagues
   visible for the current country filter, reading from the same league metadata
   already in memory.

7. **`marker.country` = first team's country; fallback to feature-level `country`
   (from `city.country`)** | Alternative: always use feature-level country |
   Reason: after the data migration all Italian teams have `team.league.country.name`.
   The feature-level fallback protects against stadiums with no teams (e.g. new
   stadium not yet assigned a team).

8. **No map.js modularisation in this PR** | Reason: additive changes only. The
   country + league additions slot into the existing `applyFilters()` pattern without
   restructuring it. Modularisation (`refactor/modularise-map-js`) remains the
   recommended follow-up task.

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/models.py` | Edit | Add `Country`, `League`; add `Team.league` FK |
| `italiastadiaapp/migrations/0021_*.py` | New | Schema migration (makemigrations) |
| `italiastadiaapp/migrations/0022_*.py` | New | Data migration (backfill Italian leagues) |
| `italiastadiaapp/admin.py` | Edit | Register `Country`, `League` |
| `italiastadiaapp/views.py` | Edit | Deeper `select_related`; add `country`, `league_id`, `division_level` to GeoJSON |
| `italiastadiaapp/templates/index.html` | Edit | Replace hardcoded `tierFilter` with empty `leagueFilter` |
| `italiastadiaapp/static/js/map.js` | Edit | Country + league filter state; dynamic dropdowns; colour + legend |
| `italiastadiaapp/tests/test_api.py` | Edit | Assert new GeoJSON fields |
| `italiastadiaapp/tests/test_models.py` | Edit | Country + League model tests |
| `CLAUDE.md` | Edit | Update GeoJSON contract |

## Implementation steps

### Layer 1 — Model + migrations

1. [ ] **models.py** — add at the top (before `City`):
   ```python
   class Country(models.Model):
       name = models.CharField(max_length=255)
       code = models.CharField(max_length=2)       # ISO 3166-1 alpha-2
       def __str__(self): return self.name

   class League(models.Model):
       name = models.CharField(max_length=255)
       country = models.ForeignKey(Country, on_delete=models.CASCADE,
                                   related_name="leagues", db_index=True)
       division_level = models.IntegerField()      # 1=top flight, 2=second, ...
       def __str__(self): return f"{self.name} ({self.country})"
   ```
   Add to `Team`:
   ```python
   league = models.ForeignKey("League", on_delete=models.SET_NULL,
                               null=True, blank=True,
                               related_name="teams", db_index=True)
   ```

2. [ ] **Schema migration** — `python manage.py makemigrations` →
   `0021_country_league_team_league.py`. Inspect: must be purely additive
   (new tables + new nullable column on Team).

3. [ ] **Data migration** — create `0022_seed_italian_leagues.py` manually:
   ```python
   from django.db import migrations

   def seed_italian_leagues(apps, schema_editor):
       Country = apps.get_model("italiastadiaapp", "Country")
       League = apps.get_model("italiastadiaapp", "League")
       Team = apps.get_model("italiastadiaapp", "Team")

       italy, _ = Country.objects.get_or_create(name="Italy", defaults={"code": "IT"})

       serie_a, _ = League.objects.get_or_create(name="Serie A", country=italy,
                                                   defaults={"division_level": 1})
       serie_b, _ = League.objects.get_or_create(name="Serie B", country=italy,
                                                   defaults={"division_level": 2})
       serie_c, _ = League.objects.get_or_create(name="Serie C", country=italy,
                                                   defaults={"division_level": 3})

       tier_to_league = {1: serie_a, 2: serie_b, 3: serie_c}
       for team in Team.objects.filter(league__isnull=True):
           if team.tier in tier_to_league:
               team.league = tier_to_league[team.tier]
               team.save(update_fields=["league"])

   def unseed_italian_leagues(apps, schema_editor):
       Country = apps.get_model("italiastadiaapp", "Country")
       Country.objects.filter(code="IT").delete()   # cascades to leagues + team FKs

   class Migration(migrations.Migration):
       dependencies = [("italiastadiaapp", "0021_country_league_team_league")]
       operations = [migrations.RunPython(seed_italian_leagues,
                                          unseed_italian_leagues)]
   ```

### Layer 2 — Admin

4. [ ] **admin.py** — add:
   ```python
   from .models import Country, League

   @admin.register(Country)
   class CountryAdmin(admin.ModelAdmin):
       list_display = ("name", "code")
       search_fields = ("name", "code")

   @admin.register(League)
   class LeagueAdmin(admin.ModelAdmin):
       list_display = ("name", "country", "division_level")
       list_filter = ("country",)
       ordering = ("country", "division_level")
   ```

### Layer 3 — API

5. [ ] **views.py `stadiums_geojson`** — update queryset:
   ```python
   Stadium.objects.select_related("city").prefetch_related(
       "teams__league__country"
   )
   ```
   Add `country` at the feature level:
   ```python
   "country": s.city.country if s.city else "",
   ```
   Add to each team dict in the teams list:
   ```python
   "league_id": t.league_id,           # FK integer, None if unset
   "league_name": t.league.name if t.league else t.get_tier_display(),
   "division_level": t.league.division_level if t.league else t.tier,
   "country": t.league.country.name if (t.league and t.league.country) else (
       s.city.country if s.city else ""
   ),
   ```
   The fallback `t.get_tier_display()` and `t.tier` mean the API degrades
   gracefully if a team somehow has no league set.

### Layer 4 — Template

6. [ ] **index.html** — in `#operationalFilters`, replace:
   ```html
   <select id="tierFilter" class="form-select w-auto">
       <option value="">All leagues</option>
       <option value="1">Serie A</option>
       <option value="2">Serie B</option>
       <option value="3">Serie C</option>
   </select>
   ```
   with:
   ```html
   <select id="countryFilter" class="form-select w-auto">
       <option value="">All countries</option>
   </select>
   <select id="leagueFilter" class="form-select w-auto">
       <option value="">All leagues</option>
   </select>
   ```
   Keep `gironeFilter` unchanged (JS will control its visibility).

### Layer 5 — JavaScript

7. [ ] **map.js top-level DOM refs** — rename/add:
   ```javascript
   // replace:  const tierFilter = document.getElementById("tierFilter");
   const countryFilter  = document.getElementById("countryFilter");
   const leagueFilter   = document.getElementById("leagueFilter");
   ```

8. [ ] **map.js marker building** (inside `fetch` callback) — add to each marker:
   ```javascript
   marker.country = props.country || "";
   marker.leagues = (props.teams || []).map(t => ({
       id:             String(t.league_id ?? ""),
       name:           t.league_name  || "",
       divisionLevel:  t.division_level ?? null,
       country:        t.country || props.country || "",
   }));
   // primary league = highest rank (lowest division_level) among this marker's teams
   const sorted = [...marker.leagues].sort(
       (a, b) => (a.divisionLevel ?? 99) - (b.divisionLevel ?? 99));
   marker.primaryLeague = sorted[0] || null;
   ```
   Remove the old `marker.tiers` and `marker.gironi` assignments — these are now
   derived on the fly inside `applyFilters()` and `getMarkerColor()`:
   ```javascript
   // keep for girone logic:
   marker.gironi = (props.teams || []).map(t => t.girone || "");
   marker.ownership = props.ownership ? String(props.ownership) : "UNKNOWN";
   ```

9. [ ] **map.js `populateCountryFilter()`** — call after all markers are built:
   ```javascript
   function populateCountryFilter() {
       const countries = [...new Set(
           markers.flatMap(m => m.leagues.map(l => l.country)).filter(Boolean)
       )].sort();
       countryFilter.innerHTML = `<option value="">All countries</option>`;
       countries.forEach(c => {
           const opt = document.createElement("option");
           opt.value = c;
           opt.textContent = c;
           countryFilter.appendChild(opt);
       });
   }
   ```

10. [ ] **map.js `populateLeagueFilter(country)`** — call when country changes and on
    initial load:
    ```javascript
    function populateLeagueFilter(country) {
        const seen = new Map();  // id → league metadata
        markers.forEach(m => {
            m.leagues.forEach(l => {
                if (!l.id) return;
                if (country && l.country !== country) return;
                if (!seen.has(l.id)) seen.set(l.id, l);
            });
        });
        // sort by division_level
        const leagues = [...seen.values()].sort(
            (a, b) => (a.divisionLevel ?? 99) - (b.divisionLevel ?? 99));

        leagueFilter.innerHTML = `<option value="">All leagues</option>`;
        leagues.forEach(l => {
            const opt = document.createElement("option");
            opt.value = l.id;
            opt.textContent = l.name;
            opt.dataset.divisionLevel = l.divisionLevel ?? "";
            opt.dataset.country = l.country;
            leagueFilter.appendChild(opt);
        });
        leagueFilter.value = "";

        // reset girone when league list changes
        gironeFilter.style.display = "none";
        gironeFilter.value = "";
    }
    ```

11. [ ] **map.js `applyFilters()`** — replace `selectedTier` block:
    ```javascript
    function applyFilters(updateStadiumDropdown = true) {
        const selectedCountry  = countryFilter.value;
        const selectedLeague   = leagueFilter.value;   // league ID string or ""
        const selectedGirone   = gironeFilter.value;
        const selectedOwnership = ownershipFilter.value;
        const selectedStadium  = stadiumFilter.value;

        let visibleMarkers = [];

        markers.forEach(marker => {
            const countryMatches =
                !selectedCountry ||
                marker.leagues.some(l => l.country === selectedCountry);

            const leagueMatches =
                !selectedLeague ||
                marker.leagues.some(l => l.id === selectedLeague);

            const gironeMatches =
                !selectedGirone ||
                marker.gironi.includes(selectedGirone);

            const ownershipMatches =
                !selectedOwnership || marker.ownership === selectedOwnership;

            const stadiumMatches =
                !selectedStadium || marker.stadiumId === selectedStadium;

            if (countryMatches && leagueMatches && gironeMatches &&
                ownershipMatches && stadiumMatches) {
                marker.addTo(map);
                visibleMarkers.push(marker);
            } else {
                map.removeLayer(marker);
            }
        });

        stadiumCounter.textContent =
            `${visibleMarkers.length} stadium${visibleMarkers.length === 1 ? "" : "s"}`;
        if (updateStadiumDropdown) updateStadiumDropdownOptions(visibleMarkers);
        closeActivePopup();
    }
    ```

12. [ ] **map.js event handlers** — replace `tierFilter` handler:
    ```javascript
    countryFilter.addEventListener("change", function () {
        stadiumFilter.value = "";
        populateLeagueFilter(this.value);
        updateLegend("operational");   // re-render with new country's leagues
        applyFilters();
    });

    leagueFilter.addEventListener("change", function () {
        const selected = leagueFilter.options[leagueFilter.selectedIndex];
        const divLevel = selected ? Number(selected.dataset.divisionLevel) : null;
        const country  = selected ? selected.dataset.country : "";

        if (divLevel === 3 && country === "Italy") {
            gironeFilter.style.display = "inline-block";
        } else {
            gironeFilter.style.display = "none";
            gironeFilter.value = "";
        }
        stadiumFilter.value = "";
        applyFilters();
    });
    ```
    Keep `gironeFilter`, `ownershipFilter`, `stadiumFilter` handlers unchanged.

13. [ ] **map.js `getMarkerColor()`** — replace the old tier-based logic:
    ```javascript
    function getMarkerColor(marker) {
        const level = marker.primaryLeague ? marker.primaryLeague.divisionLevel : null;
        const isItaly = marker.primaryLeague
            ? marker.primaryLeague.country === "Italy"
            : false;

        if (level === 1) return "#00c853";   // green  — top flight
        if (level === 2) return "#ffffff";   // white  — second tier

        if (level === 3) {
            if (isItaly) {
                const girone = marker.gironi[0];
                if (girone === "A") return "#ff8a80";
                if (girone === "B") return "#ff5252";
                if (girone === "C") return "#d50000";
            }
            return "#ff1744";               // generic third-tier red
        }

        return "#9e9e9e";                   // grey — unknown / unassigned
    }
    ```

14. [ ] **map.js `updateLegend()`** — make operational legend data-driven:
    ```javascript
    function updateLegend(mode) {
        if (!legendDiv) return;
        if (mode !== "operational") {
            // existing development legend HTML unchanged
            legendDiv.innerHTML = /* ... existing ... */;
            return;
        }

        const country = countryFilter ? countryFilter.value : "";
        // collect leagues visible in the current country selection, sorted by level
        const seen = new Map();
        markers.forEach(m => {
            m.leagues.forEach(l => {
                if (!l.id) return;
                if (country && l.country !== country) return;
                if (!seen.has(l.id)) seen.set(l.id, l);
            });
        });
        const leagues = [...seen.values()].sort(
            (a, b) => (a.divisionLevel ?? 99) - (b.divisionLevel ?? 99));

        const levelColors = { 1: "#00c853", 2: "#ffffff", 3: "#ff1744" };
        const items = leagues.map(l => {
            const color = levelColors[l.divisionLevel] || "#9e9e9e";
            return `<div class="legend-item">
                        <span class="legend-dot" style="background:${color}"></span>
                        ${l.name}
                    </div>`;
        }).join("");

        legendDiv.innerHTML = `<h6 class="legend-title">Leagues</h6>${items}`;
    }
    ```
    Call `updateLegend("operational")` after `populateCountryFilter()` on initial
    load, and again inside the `countryFilter` change handler.

### Layer 6 — Tests

15. [ ] **test_models.py** — add:
    ```python
    def test_country_and_league_str():
        country = Country(name="Italy", code="IT")
        assert str(country) == "Italy"
        league = League(name="Serie A", country=country, division_level=1)
        assert "Serie A" in str(league)
        assert "Italy" in str(league)
    ```

16. [ ] **test_api.py** — in `test_stadiums_geojson_returns_valid_feature_collection`,
    assert the first feature has `country` at the feature level AND that each team
    entry has `league_id`, `league_name`, `division_level`, `country` keys
    (values may be `None`/`""` with sparse test data — assert key presence only).

17. [ ] **CLAUDE.md** — update GeoJSON contract to show the expanded properties.

## PostgreSQL safety check

- [x] `Country.name` CharField 255 ✓
- [x] `Country.code` CharField 2 ✓
- [x] `League.name` CharField 255 ✓
- [x] `League.division_level` IntegerField (not SmallIntegerField) ✓
- [x] `Team.league` FK null=True, blank=True (pure additive column) ✓
- [x] `Team.league` FK has db_index=True ✓
- [x] Data migration uses `get_or_create` — idempotent on re-run ✓

## Test plan

- `python manage.py makemigrations --check` → exit 0
- `python manage.py migrate` → applies 0021 + 0022 cleanly
- `pytest italiastadiaapp/tests/ -v` → 7+ passed (all existing + 2 new)
- Manual: load map → `countryFilter` shows "Italy"; `leagueFilter` shows
  "Serie A / Serie B / Serie C" in that order
- Manual: select Serie C → `gironeFilter` appears; select other leagues → hidden
- Manual: select "All countries" + "All leagues" → all Italian markers visible
- Manual: add a test England fixture row via admin → select "England" →
  only English stadium shows; league dropdown shows the English league name

## Rollback plan

- Schema migration is additive (2 new tables + 1 nullable FK) — no existing data loss
- Data migration has a full `reverse_code` (`unseed_italian_leagues`) that deletes the
  Italy Country row (cascades to League rows; Team.league FK is SET_NULL)
- To revert: `python manage.py migrate italiastadiaapp 0020`
- Template + JS revert: `git revert <commit>`

## Known scope increase vs original plan

The original plan deferred making `Team.league` work for Italian teams ("European-only
for now"). The dynamic league dropdown makes that deferral impossible — the dropdown
must be populated from real data on page load, and Italian teams are the only data
that exists. The data migration (step 3) is the new critical path item. Everything
else follows from it.

`map.js` changes are larger than in the original plan (~80 lines net change) because
replacing `tierFilter` touches the marker-building loop, `applyFilters()`, two event
handlers, `getMarkerColor()`, and `updateLegend()`. Still additive in structure.

## Known tech debt introduced

`map.js` is now ~600 lines. The Phase 1 JS modularisation item
(`refactor/modularise-map-js`) becomes more pressing after this merge.
Recommended order: ship this feature → immediately open `refactor/modularise-map-js`.
