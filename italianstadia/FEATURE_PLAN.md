# Feature Plan — Sprint 2: Map interaction fixes
_Created: 2026-06-01 | Branch: fix/map-interaction_

## Problem / Goal

Four related map issues that must be resolved before any new map features are built:

1. **Marker click sometimes fails** — circleMarkers may be unresponsive in areas where
   the legend control or filter bar overlaps the canvas, or a stale `activePopup` blocks
   re-opening. Needs root-cause diagnosis before fixing.
2. **Legend is static after filtering** — `updateLegend()` is called on country change and
   mode toggle but NOT on league change. Selecting "Serie A" leaves all leagues in the
   legend. Legend should reflect only leagues that have at least one visible marker.
3. **No zoom on marker selection** — clicking a marker opens a popup but the map stays
   at its current zoom. A `map.flyTo()` to the stadium would make selection feel responsive.
4. **League filter doesn't trigger country zoom+flash** — country filter already calls
   `zoomToCountry()`; league filter has the country available in `selected.dataset.country`
   but never uses it.

Success: all four work consistently; no regression to country filter, girone filter,
ownership filter, or mode toggle.

## Scope

**In scope:**
- [ ] Diagnose and fix marker click handler reliability
- [ ] `updateLegend()` driven by visible markers, called on every filter change
- [ ] `map.flyTo()` on marker click (zoom to stadium level)
- [ ] `zoomToCountry()` called from league filter change handler

**Out of scope (do not touch):**
- Team badge DivIcon markers (Sprint 3)
- Any changes to the API, models, or views
- Development mode markers / filters
- `stadium-detail-map.js` or any detail page JS

## Design decisions

1. **Legend from visible markers, not from all markers filtered by country**
   Current: `updateLegend` iterates `markers` array and filters by `countryFilter.value`.
   New: `applyFilters` passes its `visibleMarkers` array to `updateLegend` so the legend
   always matches exactly what's on the map.
   Alternative considered: re-filter inside `updateLegend` using all active filter values.
   Rejected: duplicates filter logic; passing visible markers is the single source of truth.

2. **`flyTo` zoom level = 13, duration = 0.8s**
   Level 13 shows the stadium neighbourhood without being so tight it loses context.
   Duration 0.8s feels snappy without being jarring.
   Alternative: `fitBounds` on the marker. Rejected: circleMarkers have no geographic
   bounds; computing a fake bounds adds complexity for no benefit.

3. **League filter zoom uses the league's country, not `countryFilter.value`**
   `selected.dataset.country` is already populated when the league option is rendered.
   If the user picks "Serie A" with no country selected, we zoom to Italy anyway.
   This is the expected behaviour (mirrors country filter UX exactly).

4. **Marker click diagnosis first, code change second**
   The click issue may be CSS (`pointer-events: none` on a parent), a Leaflet z-index
   conflict with the legend control, or the `keepInView: true` popup option panning the
   map and confusing the handler. Diagnose with browser devtools before touching code.

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/static/js/map.js` | Edit | All four fixes live here |
| `italiastadiaapp/templates/index.html` | Edit (conditional) | Only if click bug is a CSS/z-index issue requiring a style fix |

## Implementation steps

1. [ ] **Diagnose click bug** — open browser devtools, inspect circleMarker element,
       check for `pointer-events: none` on any ancestor; check Leaflet pane z-indexes
       (`leaflet-marker-pane` vs `leaflet-popup-pane` vs legend control z-index).
2. [ ] **Fix click handler** — apply targeted fix based on diagnosis (z-index rule,
       CSS override, or remove `keepInView: true` if it's the culprit).
3. [ ] **Legend from visible markers** — change `updateLegend(mode)` signature to
       `updateLegend(mode, visibleMarkers = [])`. Build league set from `visibleMarkers`
       instead of from the full `markers` array. Update all call sites:
       - `applyFilters` → pass `visibleMarkers`
       - country filter `change` → pass result of `applyFilters` (refactor to return it)
       - initial load → pass all markers
       - mode toggle → no change needed (passes `"development"` or `"operational"` only)
4. [ ] **`flyTo` on marker click** — inside the `marker.on("click")` handler, after
       `openOn(map)`, add `map.flyTo([coords[1], coords[0]], 13, { duration: 0.8 })`.
5. [ ] **League filter → zoom+flash** — in the `leagueFilter` `change` handler, after
       `applyFilters()`, add:
       ```js
       if (country) zoomToCountry(country);
       ```
6. [ ] **Smoke test all filter combinations** — country, league, girone, ownership,
       stadium dropdown; mode toggle to development and back; click markers in each state.
7. [ ] **Run test suite** — no model/view changes so API and model tests should be unaffected.

## PostgreSQL safety check

N/A — no model changes.

## Test plan

**Automated:**
- `pytest italiastadiaapp/tests/ -v` — full suite must stay green (18 tests)

**Manual (browser):**
- [ ] Click 5 different markers across different zoom levels → popup opens every time
- [ ] Select "Serie A" in league filter → legend shows only Serie A
- [ ] Select "Italy" in country filter → legend unchanged from current behaviour
- [ ] Click any marker → map flies to zoom 13 centred on that stadium
- [ ] Select "Premier League" in league filter → map zooms to England, border flashes
- [ ] Select "All leagues" → map does not zoom (no country to zoom to)
- [ ] Select country then league → both zoom/flash events fire without conflict
- [ ] Toggle to development mode and back → legend resets correctly

## Rollback plan

Single JS file change. To revert:
```bash
git checkout main -- italiastadiaapp/static/js/map.js
```
No migration, no DB change, no server restart needed.
