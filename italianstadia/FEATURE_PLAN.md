# Feature Plan — Development Stadiums: Country Filter, GeoJSON Fix, Mobile Bugs
_Created: 2026-06-13 | Branch: feature/dev-stadiums-country-filter_

## Problem / Goal

The "Under Development" map mode works for Italy but has four outstanding gaps:

1. **No country in GeoJSON** — `stadium_developments_geojson` returns no `country` or `city`
   field, so the frontend has no data to build a country filter from.
2. **No country filter in development mode** — once we add European development records,
   users can't narrow to a country the way they can in operational mode.
3. **Mobile popup silent** — tapping a development marker on mobile does nothing. The
   `isMobile` constant is evaluated once at page-load (`window.innerWidth <= 768`). If the
   device loads at a slightly wider viewport the `openMobileSheet` branch is skipped and
   `bindPopup` fires instead — but Leaflet's desktop popup is invisible on touch without a
   map pan. Fix: check viewport width at click-time, not page-load time.
4. **Mobile mode switch has no labels** — the CSS at `@media (max-width: 991px)` hides both
   `.mode-label` spans entirely (`display: none`), so the toggle is a mystery slider. Users
   don't know they're switching between Operational and Under Development.

Success = development markers expose country in GeoJSON → country filter is populated and
works → tapping a dev marker on mobile opens the bottom sheet → the mode toggle on mobile
shows abbreviated labels so the user always knows which mode they are in.

---

## Scope

**In scope:**
- [ ] Add `country` CharField to `StadiumDevelopment` model + migration
- [ ] Backfill existing 10 Italian records: `country = "Italy"` via data migration
- [ ] Fix `stadium_developments_geojson`: add `select_related` + `prefetch_related`,
      expose `country`, `city`, `future_tenants` in properties
- [ ] Add country filter `<select id="developmentCountryFilter">` to `#developmentFilters`
      in `index.html`
- [ ] `map.js` — `updateDevelopmentDropdownOptions()`: populate country dropdown from markers
- [ ] `map.js` — `applyDevelopmentFilters()`: filter by selected country
- [ ] `map.js` — store `marker.country` / `marker.city` on each development marker
- [ ] Fix mobile popup: change per-marker click binding to check `window.innerWidth` at
      click-time (always `bindPopup`, open sheet inside click handler on mobile)
- [ ] Fix mobile mode switch: show short labels via `data-short` attribute +
      CSS `content: attr(data-short)` — "Ops" / "Dev" visible at ≤ 991 px
- [ ] Clear filters button also resets `developmentCountryFilter`
- [ ] Update `admin.py` to expose `country` field on `StadiumDevelopment`
- [ ] Add API test: GeoJSON includes `country` and `future_tenants` in properties

**Out of scope (do not touch):**
- Entering European development data (separate task)
- Changes to operational stadiums GeoJSON or filters
- `StadiumDevelopment` scraper / JSON data pipeline
- Mobile layout of the filter bar itself

---

## Design decisions

1. **`country` as a plain CharField on `StadiumDevelopment`, not derived from `stadium.city.country`**
   | Alternative: derive from stadium FK → stadium.city.country
   | Reason: ~40% of development records are NEW builds with no existing stadium FK. A direct
     `country` field covers all cases and lets us fill it from JSON data files for future records.
     Nullable so migration is safe.

2. **Click-time viewport check (`window.innerWidth <= 768`) instead of `isMobile` constant**
   | Alternative: re-evaluate `isMobile` with a ResizeObserver
   | Reason: simpler one-line fix, same pattern operational markers already use at line 1117.
     ResizeObserver is overkill for a map that rarely resizes mid-session.

3. **`bindPopup` always; decide sheet vs popup inside the click handler**
   | Alternative: only bind one or the other based on viewport at creation time
   | Reason: ensures desktop fallback (Leaflet popup) is always wired even if width changes;
     keeps the code symmetric with how operational markers work.

4. **`data-short` attribute + CSS `::before` for abbreviated mobile labels**
   | Alternative: JavaScript that swaps label text on resize
   | Reason: pure CSS, no JS, no layout shift. "Ops" and "Dev" fit on any phone navbar.

5. **Expose `future_tenants` as array of `{id, name, image_url}` in GeoJSON**
   | Alternative: comma-separated team name string
   | Reason: popup can render team badge images with minimal extra effort, consistent with
     the richness of the operational mode popup.

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/models.py` | Edit | Add `country` CharField to `StadiumDevelopment` |
| `italiastadiaapp/migrations/0039_…py` | New | Migration for new field + backfill data |
| `italiastadiaapp/views.py` | Edit | Fix geojson: select_related, new properties |
| `italiastadiaapp/admin.py` | Edit | Expose `country` in admin list/form |
| `italiastadiaapp/templates/index.html` | Edit | Country filter select + mobile label fix |
| `italiastadiaapp/static/js/map.js` | Edit | Country filter logic + mobile popup fix |
| `italiastadiaapp/tests/test_api.py` | Edit | Assert new GeoJSON properties |

---

## Implementation steps

1. [ ] **Model** — add `country = models.CharField(max_length=255, null=True, blank=True)`
       to `StadiumDevelopment` in `models.py`

2. [ ] **Migration** — `python manage.py makemigrations` → auto-generates field addition;
       add a `RunPython` step in the same migration to backfill `country = "Italy"` on all
       10 existing records (pk 1–10)

3. [ ] **Admin** — add `country` to `list_display` and fieldset in `admin.py`

4. [ ] **GeoJSON view** — update `stadium_developments_geojson` in `views.py`:
       - Query: `StadiumDevelopment.objects.select_related("stadium__city").prefetch_related("future_tenants")`
       - Derive country: `s.country or (s.stadium.city.country if s.stadium and s.stadium.city else "")`
       - Derive city name: `(s.stadium.city.name if s.stadium and s.stadium.city else "")`
       - Add to properties: `country`, `city`,
         `future_tenants: [{"id": t.id, "name": t.name, "image_url": t.image_url or ""} for t in s.future_tenants.all()]`

5. [ ] **Template — country filter** — add inside `#developmentFilters` in `index.html`:
       ```html
       <select id="developmentCountryFilter" class="form-select form-select-sm">
           <option value="">All countries</option>
       </select>
       ```

6. [ ] **Template — mobile labels** — add `data-short` attributes to `.mode-label` spans:
       ```html
       <span id="operationalLabel" class="mode-label active" data-short="Ops">Operational</span>
       <span id="developmentLabel" class="mode-label" data-short="Dev">Under Development</span>
       ```
       Replace the existing `@media (max-width: 991px)` label rule with:
       ```css
       .mode-switch-wrap .mode-label { font-size: 0; }
       .mode-switch-wrap .mode-label::before {
           content: attr(data-short);
           font-size: 12px;
       }
       ```

7. [ ] **map.js — grab DOM ref** — add at top-level with other filter refs:
       ```javascript
       const developmentCountryFilter = document.getElementById("developmentCountryFilter");
       ```

8. [ ] **map.js — marker data** — in `data.features.forEach`, store on each marker:
       ```javascript
       marker.country = props.country || "";
       marker.city    = props.city    || "";
       ```

9. [ ] **map.js — mobile popup fix** — replace the `if (isMobile) { … } else { … }` block
       for development markers with:
       ```javascript
       marker.bindPopup(popupContent, {
           maxWidth: 260, minWidth: 220,
           autoPan: true, autoPanPadding: [20, 20], closeButton: true
       });
       marker.on("click", function () {
           if (window.innerWidth <= 768) openMobileSheet(popupContent);
       });
       ```

10. [ ] **map.js — `updateDevelopmentDropdownOptions()`** — populate country dropdown:
        ```javascript
        const countries = [...new Set(
            developmentMarkers.map(m => m.country).filter(Boolean)
        )].sort();
        developmentCountryFilter.innerHTML = `<option value="">All countries</option>`;
        countries.forEach(c => {
            const opt = document.createElement("option");
            opt.value = opt.textContent = c;
            developmentCountryFilter.appendChild(opt);
        });
        ```

11. [ ] **map.js — `applyDevelopmentFilters()`** — add country matching:
        ```javascript
        const selectedCountry = developmentCountryFilter.value;
        // inside the forEach on developmentMarkers:
        const countryMatches = !selectedCountry || marker.country === selectedCountry;
        // include countryMatches in the combined visible check
        ```

12. [ ] **map.js — clear filters** — reset `developmentCountryFilter.value = ""`
        in the clear-filters handler (alongside status/year/stadium resets)

13. [ ] **map.js — filter event listener** — add:
        ```javascript
        developmentCountryFilter.addEventListener("change", applyDevelopmentFilters);
        ```

14. [ ] **Tests** — in `test_api.py`, add assertions to the development GeoJSON test:
        - response features[0].properties contains `country`, `city`, `future_tenants`
        - `future_tenants` is a list (can be empty)

---

## PostgreSQL safety check

- [x] `country` CharField max_length=255 — adequate for any country name
- [x] No SmallIntegerField introduced
- [x] New field is `null=True, blank=True` — safe, no default required, existing rows get NULL then backfilled
- [x] No new FK fields

---

## Test plan

- `pytest italiastadiaapp/tests/test_api.py -v -k development` — new assertions pass
- Manual desktop: switch to dev mode → click marker → Leaflet popup appears with project info
- Manual mobile (DevTools ≤ 768 px): switch to dev mode → tap marker → bottom sheet opens
- Manual mobile: look at navbar toggle → see "Ops" and "Dev" labels on each side
- Manual: select "Italy" in country filter → all 10 markers remain; clear filter → all back
- Manual: check clear-filters button resets the country dropdown

---

## Rollback plan

- Migration rollback: `python manage.py migrate italiastadiaapp 0038_add_lastrefresh`
  (removes the `country` column; safe — nullable with no dependent FKs)
- JS/template rollback: `git revert` the single commit — no DB changes involved
