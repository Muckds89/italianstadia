# Feature plan — Data Insight pages (CTR / SEO play)

## Goal
Lift CTR (currently ~0.3%) by adding indexable, share-worthy "insight" pages that turn the
existing stadium dataset into stories + maps people search for. Each page = original
long-form text (SEO/AEO) + a focused map view, reusing the existing map + export stack.

## Pages (v1)
1. **National-team-only grounds** — stadiums used exclusively by a national team (no club tenant).
2. **Stadium density per population** — stadiums per million people, by country (choropleth + ranking).
3. **Artificial vs natural grass in Europe** — pitch-surface split, by country and overall.

## Schema reality (verified against models.py + live DB)
- **`Stadium.surface` ALREADY EXISTS** (choices GRASS/ARTIFICIAL/HYBRID) and is ~65% populated:
  of 774 stadiums — GRASS 348, HYBRID 103, ARTIFICIAL 56, **null 267**. ⇒ Page 3 needs **no
  schema change**; just a view + optional backfill of the 267 nulls (scrape Wikipedia "Surface").
- **`Country` has NO `population`** — the `population` field is on **`City`**, not `Country`
  (`Country` fields: code, name, uefa_rank). ⇒ Page 2 must add `Country.population` + backfill
  (static dict via data migration is simplest; do NOT sum City populations — coverage is partial).
- Page 1 needs no new fields (derives from team links).

---

## Architecture (reuse, don't reinvent)
- **One new view module section** in `views.py` (`insights_index`, `insight_national`,
  `insight_density`, `insight_surface`) + URL patterns under `/insights/...` (namespaced).
- **Data endpoints**: reuse the GeoJSON pattern. Either add `?view=national|surface` params to
  the existing `stadiums_geojson`, or add thin dedicated endpoints. Prefer **params on the
  existing endpoint** (less surface area, already cached).
- **Maps**: reuse `map.js` modes. It already supports `color_by` (surface/country/...) and a
  filtered FeatureCollection — add an `insightMode` init from a `data-` attribute so each
  insight page boots the shared map with a preset filter + legend, no new JS file ideally.
- **Choropleth (page 2)**: this is the one genuinely new map style (country fill by value,
  not point markers). Two options:
  - (a) Leaflet country polygons filled by density, using the **`countries_hires.geojson`**
    we just added (names normalized). Lightweight, on-brand.
  - (b) Static backend-rendered PNG via the export stack (`_compose_export_image`) like the
    tournament maps. Cheaper at runtime (512 MB dyno), regenerated on data change.
  Recommend (a) for interactivity; fall back to (b) if memory is a concern.
- **SEO**: each page gets data-aware long-form prose (like `tournament_about`), JSON-LD
  (`Dataset` or `ItemList`), `<meta>` description, and an entry in `sitemap.py`. Cross-link
  from the map and from each other ("Related insights").
- **Caching**: `@cache_page(60*60)` on each view (matches tournament/geojson pattern).

---

## Page 1 — National-team-only grounds
- **Data**: stadiums whose tenants are national teams only (no club `teams`). National teams
  are already modeled (England/France/... with flagcdn badges, `tournaments`). Define
  "national-only" = stadium has ≥1 national-team association and 0 club teams. Verify how
  national teams attach to a stadium (FK / future-tenant link used for Wembley etc.).
- **Map**: filtered marker set, badge = national flag (reuse `_country_flag_code`).
- **Text**: list the grounds, which nation, capacity; note shared vs dedicated national stadiums.
- **Effort**: S (no schema change). Mostly a query + filtered GeoJSON + template.

## Page 2 — Stadium density per population
- **Data**: per country: `count(stadiums) / Country.population * 1e6`. Needs `Country.population`
  (add `IntegerField(null=True)` + backfill via a data migration from a static dict or scrape).
  Decide the denominator set: all stadiums in DB vs top-N-tier only (document the choice).
- **Map**: choropleth over `countries_hires.geojson` (option a above) + a sortable ranking table.
- **Text**: "X has the most stadiums per capita…", caveats (dataset coverage varies by country).
- **Effort**: M (Country.population add + backfill + choropleth rendering).

## Page 3 — Artificial vs natural grass
- **No schema change** — `Stadium.surface` already exists and is 66% populated (507/774).
- **Backfill (optional, recommended)**: 267 stadiums have `surface=None`. Add Wikipedia
  infobox "Surface" scraping to `scrape_stadium` going forward, plus a one-off backfill
  command for existing nulls (map "grass"→GRASS, "artificial turf"/"3G/4G"→ARTIFICIAL,
  "hybrid"/"GrassMaster"/"SISGrass"→HYBRID). Until then, exclude nulls from the % and
  label them "unknown" so the stats stay honest.
- **Map**: `color_by=surface` (already supported in the export legend) — green/amber/teal.
- **Text**: overall %, by-country split, note climate / lower-tier correlation.
- **Effort**: S–M (no schema; view + filtered GeoJSON now, backfill is the optional long pole).

---

## Suggested order
1. **Page 1** (no schema, fast win, ships the `/insights/` shell + shared insight template).
2. **Page 3** (surface already exists + populated — quick second win; backfill later).
3. **Page 2** (needs `Country.population` add + backfill + the new choropleth style — do last).

## Cross-cutting / done-criteria
- `/insights/` index page linking all three; nav entry; internal links from map + tournaments.
- Each page: long-form text, JSON-LD, meta description, sitemap entry, `cache_page`.
- Tests: one render test per page (200 + key content), one for each new GeoJSON param.
- Regenerate any backend PNGs if option (b) is used; document in the "Regenerate derived
  artifacts" section of CLAUDE.md.

## Open questions for you
- Page 2 denominator: **all** stadiums in DB, or only top-flight? (coverage is uneven by country)
- Choropleth: interactive Leaflet (a) or static export PNG (b)?
- Page 3: is backfilling surface for existing rows worth it now, or scrape-forward only +
  hide unknowns?
