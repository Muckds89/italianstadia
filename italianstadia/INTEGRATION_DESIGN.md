# Integration Design — Multi-League Scraper + Map Enhancements
_Created: 2026-05-26 | Branch: scraper/multi-league-transfermarkt_

## Purpose

Two parallel workstreams delivered together:

1. **Scraper** — extend `scripts/populate_data_from_transfermrkt.py` to scrape any European
   league (not just Italian Serie A/B/C), resolving the correct `Country` + `League` DB rows
   and setting `Team.league` FK automatically.

2. **Map** — three visual upgrades that only make sense once multi-league data is in DB:
   national flag colors on markers, lower-tier grey-out by default, country zoom + border flash
   on country selection.

---

# Part 1 — Scraper

## Current state (what breaks for non-Italian leagues)

| Location | Hardcoded assumption | Must become |
|---|---|---|
| `scrape_city()` line 507 | `country = "Italy"` | Read from league config |
| `scrape_team()` line 898 | `tier` pulled from JSON | Derived from `League.division_level` |
| `scrape_team()` line 899 | `girone` from JSON | Only set for Italy div 3 |
| `scrape_team()` line 914 | Scrapes "Italian Champion" XPath | Guard behind `league.country.name == "Italy"` |
| `scrape_average_attendance()` line 813 | XPath targets `"24/25"` | Configurable per-league season string |
| `run()` line 1006 | Reads `transfermrkt_urls_with_girone.json` | Per-league JSON via CLI arg |
| `scrape_team()` | Never sets `Team.league` FK | Set on every `update_or_create` |

## Data flow

```
scripts/data/urls_<league_slug>.json      ← per-league input file (manually curated)
  → populate_data_from_transfermrkt.py    ← single parameterised script
      resolve_league(config)              ← get_or_create Country + League in DB
      scrape_city(city_data, country)     ← City.update_or_create
      scrape_stadium(stadium_data, city)  ← Stadium.update_or_create
      scrape_team(team_data, stadium,     ← Team.update_or_create
                  city, league, season)       + Team.league = league FK
  → italiastadiaapp DB (SQLite/Postgres)
  → /api/stadiums/ GeoJSON endpoint
  → map.js countryFilter / leagueFilter
```

## Input file format

One JSON file per league, stored in `scripts/data/`. Filename: `urls_<league_slug>.json`.

```json
{
  "league": {
    "name": "Premier League",
    "country": "England",
    "country_code": "GB",
    "division_level": 1,
    "season": "24/25"
  },
  "teams": [
    {
      "name": "Arsenal",
      "transfermarkt_url": "https://www.transfermarkt.com/fc-arsenal/startseite/verein/11",
      "transfermarkt_attendance_url": "https://www.transfermarkt.com/fc-arsenal/besucherzahlen/verein/11",
      "wikipedia_url": "https://en.wikipedia.org/wiki/Arsenal_F.C.",
      "stadium": {
        "name": "Emirates Stadium",
        "transfermarkt_url": "https://www.transfermarkt.com/emirates-stadium/stadion/stadion/290",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Emirates_Stadium",
        "city": {
          "name": "London",
          "wikipedia_url": "https://en.wikipedia.org/wiki/London"
        }
      }
    }
  ]
}
```

**Key differences from current `transfermrkt_urls_with_girone.json`:**
- Top-level `"league"` object replaces implicit Italy assumption.
- `"season"` string replaces hardcoded XPath season string.
- `"country_code"` added for `Country.code` (ISO 3166-1 alpha-2).
- `"girone"` removed — Italy Serie C only, handled in code.
- No `"tier"` field — derived from `league.division_level`.

Existing `transfermrkt_urls_with_girone.json` stays unchanged; Italian leagues migrate to
`urls_serie_a.json`, `urls_serie_b.json`, `urls_serie_c.json`.

## CLI interface

```bash
python scripts/populate_data_from_transfermrkt.py --league premier-league
# slug → scripts/data/urls_premier_league.json
```

```python
import argparse
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--league", required=True)
    args = parser.parse_args()
    run(args.league)
```

## New function: `resolve_league(config)`

```python
def resolve_league(config):
    from italiastadiaapp.models import Country, League
    country, _ = Country.objects.get_or_create(
        name=config["country"],
        defaults={"code": config["country_code"]},
    )
    league, _ = League.objects.get_or_create(
        name=config["name"],
        country=country,
        defaults={"division_level": config["division_level"]},
    )
    return league
```

## Changes to `scrape_city(city_data, country)`

Replace hardcoded `"Italy"` with the `country` parameter from league config.

## Changes to `scrape_team(team_data, stadium, city, league, season)`

```python
tier = league.division_level                    # no longer from JSON

girone = None
if league.country.name == "Italy" and league.division_level == 3:
    girone = team_data.get("girone")            # Italy Serie C only

num_of_titles = 0
if league.country.name == "Italy":
    # existing "Italian Champion" XPath scraping
    ...

# FK set on save
Team.objects.update_or_create(name=team_name, defaults={
    ..., "tier": tier, "girone": girone, "league": league,
})
```

## Changes to `scrape_average_attendance(attendance_url, season)`

```python
# Before
"//tr[td[contains(text(), '24/25')]]"
# After
f"//tr[td[contains(text(), '{season}')]]"
```

## Rate limiting

- Max 1 request / 2 s to Transfermarkt (Selenium `time.sleep(2)` already in place)
- Do not run multiple leagues in parallel
- On 429: add exponential back-off; do not retry blindly

---

# Part 2 — Map enhancements

## Feature A — National flag colors on markers

### Design

Replace the current hardcoded `LEVEL_COLORS = {1: green, 2: white, 3: red}` with a
`COUNTRY_COLORS` map. Each country's list is ordered by flag color top-to-bottom;
index 0 = division_level 1, index 1 = division_level 2, etc.

```javascript
// map.js — replaces LEVEL_COLORS
const COUNTRY_COLORS = {
    "Italy":       ["#009246", "#ffffff", "#ce2b37"],  // green · white · red
    "Germany":     ["#333333", "#dd0000", "#ffce00"],  // black* · red · gold
    "England":     ["#cf081f", "#ffffff", "#003087"],  // red · white · blue
    "France":      ["#002395", "#ffffff", "#ed2939"],  // blue · white · red
    "Spain":       ["#aa151b", "#f1bf00"],              // red · yellow
    "Netherlands": ["#ae1c28", "#ffffff", "#21468b"],  // red · white · blue
    "Portugal":    ["#006600", "#ff0000"],              // green · red
    "Scotland":    ["#005eb8", "#ffffff"],              // blue · white
    "Turkey":      ["#e30a17", "#ffffff"],              // red · white
    "Belgium":     ["#fdda24", "#000000", "#ef3340"],  // yellow* · black · red
};
// * Germany black → #333333 and Belgium black → #000000 would be invisible on the dark
//   CartoDB basemap. Germany div-1 uses #333333 (dark grey) with a gold border stroke.
//   Belgium div-1 uses yellow as its most distinctive flag color.
```

**Marker border stroke** — all markers already have `color: "#111111"` as outline. For
Germany div-1 (`#333333` fill) and any other near-black colors, override `color` to `"#ffce00"`
(gold) so the marker is still legible on the dark basemap.

```javascript
function getMarkerStyle(marker) {
    const primary = marker.primaryLeague;
    const level   = primary ? primary.divisionLevel : null;
    const country = primary ? primary.country : null;

    const fillColor = getMarkerColor(marker);

    // Give near-black fills a contrasting stroke
    const needsBrightStroke = fillColor === "#333333" || fillColor === "#000000";
    const strokeColor = needsBrightStroke ? "#ffce00" : "#111111";

    return { fillColor, color: strokeColor };
}

function getMarkerColor(marker) {
    const primary = marker.primaryLeague;
    const level   = primary ? primary.divisionLevel : null;
    const country = primary ? primary.country : null;

    const colors = COUNTRY_COLORS[country];
    if (colors && level != null && level >= 1) {
        return colors[level - 1] || "#9e9e9e";
    }
    return "#9e9e9e";
}
```

**Italy Serie C girone sub-colors** are dropped — the three shades of red were only
meaningful when Italy was the only country. With multi-country data they add confusion;
all Serie C markers use the same Italian flag red `#ce2b37`.

**`updateLegend()`** — already data-driven from `markers[].leagues`; no structural change
needed. Only the color lookup changes from `LEVEL_COLORS[divisionLevel]` to
`COUNTRY_COLORS[country]?.[divisionLevel - 1]`.

---

## Feature B — Lower tiers greyed out by default

### Design

By default (no country or league filter active), only top-flight markers (division_level = 1)
show their flag color. Tiers 2+ are visible but grey, reducing clutter when 5+ countries
are loaded simultaneously. When the user picks a country or league, all visible markers
switch to their real flag color.

```javascript
function getMarkerColor(marker) {
    const primary = marker.primaryLeague;
    const level   = primary ? primary.divisionLevel : null;
    const country = primary ? primary.country : null;

    const filterActive = countryFilter.value || leagueFilter.value;

    // Grey out lower tiers when no filter is active
    if (!filterActive && level !== 1) return "#9e9e9e";

    const colors = COUNTRY_COLORS[country];
    if (colors && level != null) return colors[level - 1] || "#9e9e9e";
    return "#9e9e9e";
}
```

**`applyFilters()` must call `marker.setStyle(getMarkerStyle(marker))`** after deciding
visibility, so colors update live when filters change. Currently markers only have their
color set once at load time.

```javascript
// Inside applyFilters() forEach loop:
if (countryMatches && leagueMatches && gironeMatches && ownershipMatches && stadiumMatches) {
    marker.setStyle(getMarkerStyle(marker));   // ← refresh color
    marker.addTo(map);
    visibleMarkers.push(marker);
} else {
    map.removeLayer(marker);
}
```

---

## Feature C — Country zoom + border flash

### Design

When a country is selected in `countryFilter`, the map:
1. Zooms to a pre-defined bounding box for that country.
2. Briefly overlays the country's border as a pulsing white polygon, then fades it out.

No external API call at selection time. Country boundaries are loaded once from a static
GeoJSON file served from Django's static files.

### Bounding boxes (for the zoom)

```javascript
// map.js
const COUNTRY_BOUNDS = {
    "Italy":       [[36.6,  6.6], [47.1, 18.5]],
    "Germany":     [[47.3,  5.9], [55.1, 15.0]],
    "England":     [[49.9, -5.7], [55.8,  1.8]],
    "France":      [[41.3, -5.1], [51.1,  9.6]],
    "Spain":       [[36.0, -9.3], [43.8,  4.3]],
    "Netherlands": [[50.8,  3.4], [53.5,  7.2]],
    "Portugal":    [[36.9, -9.5], [42.2, -6.2]],
    "Scotland":    [[54.6, -7.6], [60.9, -0.7]],
    "Turkey":      [[36.0, 26.0], [42.1, 44.8]],
    "Belgium":     [[49.5,  2.5], [51.5,  6.4]],
};
```

### Country boundary GeoJSON (for the flash)

Source: **Natural Earth 110m admin-0** — `ne_110m_admin_0_countries.geojson`.
Served as a Django static file at `italiastadiaapp/static/data/ne_110m_admin_0_countries.geojson`.
Size: ~800 KB uncompressed (simplified polygons, acceptable for a one-time load).

Loaded lazily on the first country selection:

```javascript
let countryGeoJSON = null;   // cached after first load
let flashLayer    = null;

async function loadCountryGeoJSON() {
    if (countryGeoJSON) return countryGeoJSON;
    const url = document.getElementById("map").dataset.countriesUrl;  // injected by template
    const res = await fetch(url);
    countryGeoJSON = await res.json();
    return countryGeoJSON;
}
```

The `data-countries-url` attribute is rendered by `index.html`:

```html
<!-- index.html -->
<div id="map" data-countries-url="{% static 'data/ne_110m_admin_0_countries.geojson' %}"></div>
```

### Name mapping

Natural Earth uses `ADMIN` property for country name. Some of our `Country.name` values
differ:

```javascript
const NE_NAME_MAP = {
    "England":  "United Kingdom",
    "Scotland": "United Kingdom",   // flash the whole UK when Scotland selected
};
```

### Zoom + flash implementation

```javascript
async function zoomToCountry(countryName) {
    // 1. Zoom to bounding box immediately (no async wait)
    const bounds = COUNTRY_BOUNDS[countryName];
    if (bounds) map.fitBounds(bounds, { padding: [40, 40], duration: 0.6 });

    // 2. Load GeoJSON once, then flash the border
    const geojson = await loadCountryGeoJSON();
    const neName  = NE_NAME_MAP[countryName] || countryName;
    const feature = geojson.features.find(f => f.properties.ADMIN === neName);
    if (!feature) return;

    if (flashLayer) { map.removeLayer(flashLayer); flashLayer = null; }

    flashLayer = L.geoJSON(feature, {
        style: {
            color: "#ffffff",
            weight: 2.5,
            opacity: 0.9,
            fillColor: "#ffffff",
            fillOpacity: 0.12,
            dashArray: "6 4",
        }
    }).addTo(map);

    // Fade out after 1.8 s
    setTimeout(() => {
        if (flashLayer) { map.removeLayer(flashLayer); flashLayer = null; }
    }, 1800);
}
```

### Hook into `countryFilter` change handler

```javascript
countryFilter.addEventListener("change", function () {
    const country = this.value;
    stadiumFilter.value = "";
    populateLeagueFilter(country);
    updateLegend("operational");
    applyFilters();                    // existing
    if (country) zoomToCountry(country);   // new
    else map.setView([42.5, 12.5], 5);     // reset to Europe view
});
```

---

# Files that will change

| File | Change type | Why |
|---|---|---|
| `scripts/populate_data_from_transfermrkt.py` | Edit | Parameterise all Italy-specific assumptions |
| `scripts/data/urls_serie_a.json` | Create | Migrate existing Serie A JSON to new format |
| `scripts/data/urls_serie_b.json` | Create | Migrate existing Serie B JSON to new format |
| `scripts/data/urls_serie_c.json` | Create | Migrate existing Serie C JSON to new format |
| `scripts/data/urls_premier_league.json` | Create | First non-Italian league input file |
| `italiastadiaapp/static/js/map.js` | Edit | Flag colors, grey-out, zoom + flash |
| `italiastadiaapp/static/data/ne_110m_admin_0_countries.geojson` | Create | Country boundary polygons for flash |
| `italiastadiaapp/templates/index.html` | Edit | Add `data-countries-url` attr to `#map` div |

No model changes. No migrations.

---

# Implementation steps

### Scraper (do first — map features need real data to test)

1. [ ] Create `scripts/data/` directory
2. [ ] Migrate `transfermrkt_urls_with_girone.json` → `urls_serie_a.json`, `urls_serie_b.json`, `urls_serie_c.json` with new `"league"` block
3. [ ] Add `argparse` CLI + update `run()` to load from `scripts/data/<slug>.json`
4. [ ] Add `resolve_league(config)` function
5. [ ] Update `scrape_city()` to accept `country` parameter
6. [ ] Update `scrape_team()` to accept `league` + `season`; derive `tier` and `girone`; set `Team.league`
7. [ ] Guard "Italian Champion" XPath behind `league.country.name == "Italy"`
8. [ ] Parameterise attendance season string
9. [ ] Smoke-test `--league serie-a` — must produce identical DB output to current script
10. [ ] Manually curate `urls_premier_league.json` (20 teams)
11. [ ] Run `--league premier-league`, review log, fix parse failures

### Map — flag colors (Feature A)

12. [ ] Replace `LEVEL_COLORS` with `COUNTRY_COLORS` in `map.js`
13. [ ] Rewrite `getMarkerColor()` to look up `COUNTRY_COLORS[country][level - 1]`
14. [ ] Add `getMarkerStyle()` to return both `fillColor` and `color` (stroke); handle near-black fills
15. [ ] Update all `marker.setStyle(...)` call sites to use `getMarkerStyle(marker)`
16. [ ] Remove Italy Serie C girone sub-colors; all Serie C → single `#ce2b37`
17. [ ] Update `updateLegend()` color lookup to use `COUNTRY_COLORS`

### Map — lower-tier grey-out (Feature B)

18. [ ] Add `filterActive` check to `getMarkerColor()` — return `#9e9e9e` for div 2+ when no filter
19. [ ] Call `marker.setStyle(getMarkerStyle(marker))` inside `applyFilters()` loop so colors refresh on filter change

### Map — country zoom + flash (Feature C)

20. [ ] Download `ne_110m_admin_0_countries.geojson` and place in `italiastadiaapp/static/data/`
21. [ ] Add `data-countries-url="{% static '...' %}"` to `#map` div in `index.html`
22. [ ] Add `COUNTRY_BOUNDS`, `NE_NAME_MAP`, `loadCountryGeoJSON()`, `zoomToCountry()` to `map.js`
23. [ ] Hook `zoomToCountry()` into `countryFilter` change handler; reset view on "All countries"
24. [ ] Test: select Germany → map zooms to Germany, border flashes, markers turn flag colors; deselect → map resets to Europe view, markers grey out lower tiers again

### Final

25. [ ] Run full test suite — no Python tests should break (no model/API changes)
26. [ ] Bump `map.js` cache buster (currently `?v=9` → `?v=10`)

---

# Out of scope

- Season-by-season historical data (`TeamSeasonRecord` — Phase 3)
- Automatic discovery of team URLs (always manual curation)
- Mobile-specific marker tap UX for the flash effect
- Leagues beyond the 10 in `COUNTRY_COLORS` (add to dict one at a time as data is scraped)

## Data contract (non-negotiable)
| Field | Rule | Violation = |
|-------|------|-------------|
| `Stadium.latitude/longitude` | Must be non-null | Block save, log ERROR |
| `Stadium.image_url` | Must be non-null | Log WARN, use og:image fallback |
| `Team.average_attendance` | NULL if not found, never 0 | 0 → convert to NULL |
| `Stadium.ownership` | Never UNKNOWN when owner_raw present | Classify as PRIVATE |
| `City.population` | NULL if not found | Log WARN |
| All JSON URLs | Must return HTTP 200 | Abort dry-run with list of 404s |
