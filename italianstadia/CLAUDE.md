# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Interactive web map dashboard of Italian football stadiums (Serie A/B/C), planned to expand to European leagues. Built with Django 5.1 + SQLite (dev) / PostgreSQL (prod) + Leaflet.js + Bootstrap 5. Deployed on Render at https://italianstadia-2.onrender.com

## Commands

```bash
# Activate virtual environment (Windows)
my_django_env\Scripts\activate

# Run dev server
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Load seed data
python manage.py loaddata italiastadiaapp/fixtures/initial_data.json

# Tests
pytest                                              # all tests
pytest italiastadiaapp/tests/test_api.py -v        # API only
pytest -k "stadium" -v                              # filter by name

# Static files
python manage.py collectstatic --noinput

# Populate data from scripts (not management commands)
python scripts/populate_data.py
python scripts/populate_data_from_transfermrkt.py

# Validate Wikipedia URLs in a league JSON file before scraping
python -X utf8 scripts/validate_wiki_urls.py scripts/data/urls_<league>.json --skip-cities
# Exit 0 = all OK; exit 1 = broken URLs found (do NOT run the scraper until fixed)
```

## Architecture

```
italianstadia/          ← Django project config (settings, root urls)
italiastadiaapp/        ← single Django app
  models.py             ← City, Stadium, Team, StadiumDevelopment
  views.py              ← all views: page views + GeoJSON endpoints (plain JsonResponse, no DRF)
  urls.py               ← all URL patterns (app_name = "italiastadiaapp")
  admin.py
  templates/            ← templates live here (APP_DIRS=True)
    index.html          ← map dashboard (entry point)
    stadium_detail.html
    stadium_list.html
    team_list.html
    city_list.html
    stadium_development_detail.html
  static/
    js/
      map.js                    ← Leaflet init, markers, filters, popups (all in one)
      stadium-detail-map.js     ← mini-map on stadium detail page
    css/
  tests/
    test_api.py
    test_models.py
    test_views.py
  fixtures/
    initial_data.json
scripts/                ← standalone data population scripts (not Django management commands)
  populate_data.py
  populate_data_from_transfermrkt.py
build.sh                ← Render deploy: pip install + migrate + collectstatic (NO loaddata!)
                          # The fixture is loaded MANUALLY/once, not on deploy. To
                          # correct production data, write a DATA MIGRATION (runs via
                          # `migrate` on every deploy) — editing initial_data.json alone
                          # does NOT reach production.
```

## Data model

```
Country (name unique, code unique[ISO-2])
  └── League (name, country FK, division_level[1=top flight, 2=second, ...])

City (name, population, country CharField, wikipedia_url, image_url, description)
  └── Stadium (name, capacity, address, year_of_construction, latitude, longitude,
               ownership[PUBLIC/PRIVATE/MIXED/UNKNOWN], owner_raw,
               wikipedia_url, transfermarkt_url, image_url, description)
        └── Team (name, tier[1=A/2=B/3=C], girone[A/B/C], founded, manager,
                  num_of_titles, average_attendance, stadium FK, city FK,
                  league FK → League (nullable), wikipedia_url, transfermarkt_url,
                  image_url, under_development_stadium FK → StadiumDevelopment)
StadiumDevelopment (name, project_type[NEW/REDEVELOPMENT/EXPANSION],
                    status[PLANNING/APPROVED/UNDER_CONSTRUCTION/ON_HOLD/COMPLETED],
                    future_capacity, estimated_opening, latitude, longitude,
                    architect, developer, source_url, notes, image_url,
                    stadium FK → existing Stadium if redevelopment)
```

Stadium `tier` filtering is derived from the teams that play there — `stadium_list` view groups stadiums by `{team.tier for team in stadium.teams.all()}`. For the map filter, country and league are derived from `Team.league FK → League → Country`.

## GeoJSON endpoints

- `GET /api/stadiums/` → `stadiums_geojson` — FeatureCollection with teams array in `properties`
- `GET /api/stadium-developments/` → `stadium_developments_geojson` — FeatureCollection for planned/under-construction stadiums

Both endpoints return `[longitude, latitude]` coordinates (GeoJSON standard). Current `/api/stadiums/` response shape:

```json
{
  "type": "FeatureCollection",
  "features": [{
    "type": "Feature",
    "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
    "properties": {
      "id": 1, "name": "...", "capacity": 80000,
      "city": "Milan", "country": "Italy",
      "ownership": "PUBLIC", "owner_raw": "...",
      "wikipedia_url": "...", "transfermarkt_url": "...",
      "teams": [{
        "id": 1, "name": "...",
        "tier": 1, "tier_name": "Serie A", "girone": "",
        "league_id": 1, "league_name": "Serie A",
        "division_level": 1, "country": "Italy",
        "country_rank": 1,
        "image_url": "https://...",
        "wikipedia_url": "...", "transfermarkt_url": "..."
      }]
    }
  }]
}
```

The `stadiums_geojson` view uses `select_related("city").prefetch_related("teams__league__country")`. `DecimalField` coordinates are cast to `float()` before serialisation so they come out as JSON numbers, not strings.

### Server-side filter parameters (stadiums endpoint)

`GET /api/stadiums/?country=Italy&league=Serie+A&ownership=PUBLIC`

| Param | Filters on | Example |
|-------|-----------|---------|
| `country` | `teams__league__country__name` | `Italy` |
| `league` | `teams__league__name` | `Serie+A` |
| `ownership` | `Stadium.ownership` (uppercased) | `PUBLIC` |

`map.js` fetches with **no parameters** and filters client-side (fast for ≤500 stadiums). Server-side params exist for external consumers and for the Phase 2 scale-up.

**Performance threshold:** ~173ms at 170 stadiums (SQLite). When the dataset reaches ~500+ stadiums (Phase 2 multi-league), re-benchmark — if response time exceeds 500ms, switch `map.js` to use server-side params and drop the client-side filter loop.

## Frontend (map.js)

All filter state and map logic lives in `map.js` as a single file. Filter DOM elements are grabbed at top-level; the map supports two modes: `"operational"` (default, shows Stadium markers) and `"development"` (shows StadiumDevelopment markers). `currentLayerMode` tracks this.

When adding filter logic, keep all filter state local to `applyFilters()` / `applyDevelopmentFilters()` — do not scatter state across individual event handlers. Each event handler calls one of those two functions, nothing else.

API URLs are currently hardcoded in `map.js` (`fetch("/api/stadiums/")`). When this is fixed, they should come from `data-url` attributes on DOM elements, not hardcoded strings.

## Database setup

- **Local dev:** SQLite (auto, no config needed). `db.sqlite3` is in repo root.
- **Production:** `DATABASE_URL` env var activates PostgreSQL via `dj_database_url`. SSL is required when `DATABASE_URL` is set.
- No docker-compose. Just set `DATABASE_URL` in `.env` to use a local Postgres instead of SQLite.

## Critical constraints

### PostgreSQL field limits

Always use these rules when adding fields — violations cause silent truncation or `DataError` in production:

```python
# BAD — breaks if scraped name exceeds 100 chars
name = models.CharField(max_length=100)

# GOOD
name = models.CharField(max_length=255)                            # names, titles
description = models.TextField(blank=True)                         # free text
url = models.URLField(max_length=1000)                             # image_url pattern — keep consistent
coordinates = models.DecimalField(max_digits=9, decimal_places=6)  # not FloatField
capacity = models.IntegerField(null=True, blank=True)              # not SmallIntegerField (max 32767)

# Always add db_index=True on ForeignKey fields used in filter() calls
league = models.ForeignKey(League, on_delete=models.SET_NULL, null=True, db_index=True)
```

Scraped fields that may be missing **must** have `blank=True, null=True` — a `None` from a scraper will raise `IntegrityError` otherwise.

### Tournament country flags

`COUNTRY_FLAGS` in `views.py` maps country names to emoji flags for the tournament detail page. It currently covers England, Wales, Scotland, Ireland, Italy, Turkey. **Extend this dict whenever a new host country is added to a tournament** — missing entries render as an empty string (no flag shown, not an error).

### Auto-slug constraint (Stadium and Team)

`Stadium.slug` and `Team.slug` are both `unique=True` but not `null=True`. Each model's `save()` auto-generates the slug, so normal ORM usage (`create()`, `get_or_create()`, `save()`) is safe. **Never use `bulk_create()` on Stadium or Team** — it bypasses `save()`, leaving slugs as `""`, and the second such row violates the `UNIQUE` constraint.

### N+1 query prevention

All views that iterate over related objects must use `select_related` / `prefetch_related`:

```python
# BAD — fires one query per stadium to get city
Stadium.objects.all()

# GOOD
Stadium.objects.select_related("city").prefetch_related("teams")
```

`stadium_list`, `team_list`, `stadiums_geojson`, and `stadium_detail` already follow this pattern. Keep it on any new view.

### Template lookup

`APP_DIRS=True` and `DIRS=[]`, so templates must be in `italiastadiaapp/templates/`. All views render with no subdirectory prefix — `render(request, "index.html")`, not `render(request, "italiastadiaapp/index.html")`.

### URL reversal in tests

All URL names must use the `italiastadiaapp` namespace: `reverse("italiastadiaapp:stadiums_geojson")`. Even though the root urlconf uses `include('italiastadiaapp.urls')` without an explicit namespace kwarg, Django still applies the `app_name` from the included module as the namespace — bare names like `reverse("stadiums_geojson")` will raise `NoReverseMatch`.

## Adding a new country / league

Scraping a new country requires **zero JS changes**. The map auto-adapts:

- Country zoom uses marker positions dynamically (`L.featureGroup(countryMarkers).getBounds()`) — no entry needed in `COUNTRY_BOUNDS`
- Country filter is built from the GeoJSON response, not a hardcoded list
- `COUNTRY_BOUNDS` in `map.js` is a fallback-only table (covers all 51 UEFA nations) used only when no markers exist for a country yet — do not add new entries to it

The only required steps when adding a league:
1. Create `scripts/data/urls_<slug>.json` with the correct `country_code` (ISO-2)
2. **Validate all Wikipedia URLs first:** `python -X utf8 scripts/validate_wiki_urls.py scripts/data/urls_<slug>.json --skip-cities`
   - Exit 0 = all URLs OK → safe to scrape
   - Exit 1 = broken URLs → fix JSON, re-validate, then scrape
3. Run `python scripts/populate_data_from_transfermrkt.py --league <slug>`
4. Verify no `[Ownership UNKNOWN]` warnings in the scrape log

## What NOT to do

- Do not put business logic in templates
- Do not query the DB in a template tag or loop
- Do not use `CharField(max_length=100)` for scraped content
- Do not add inline `<script>` blocks to templates — put JS in `static/js/`
- Do not skip migrations — always run `makemigrations` after model changes
- Do not hardcode API URLs in JS — use `data-url` attributes rendered by the template

## Roadmap context

The project is currently Italy-only (Serie A/B/C). Full roadmap in `italianstadia_ROADMAP.md`.

**Planned expansions:**

| Phase | Work |
|-------|------|
| Phase 2 | `Country` ✓, `League` ✓ models live; scrape European data; `TeamSeasonRecord` |
| Phase 3 | Historical season filtering via `TeamSeasonRecord(team, league, season_year)` |
| Phase 4 | Mobile-first UI, PWA |
| Phase 5 | Stadium depth (timelines, search, rankings) |

**Phase 2 leagues (priority order):**

| League | Country | Division | Status |
|--------|---------|----------|--------|
| Serie A/B/C | Italy | 1–3 | ✓ live |
| Premier League | England | 1 | JSON ready (25/26) |
| EFL Championship | England | 2 | JSON ready (25/26) |
| EFL League One | England | 3 | JSON ready (25/26) |
| Bundesliga | Germany | 1 | JSON ready (25/26) |
| 2. Bundesliga | Germany | 2 | JSON ready (25/26) |
| Primeira Liga | Portugal | 1 | JSON ready (25/26) |
| Ekstraklasa | Poland | 1 | JSON ready (25/26) |
| La Liga | Spain | 1 | JSON ready (25/26) |
| Segunda División | Spain | 2 | JSON ready (25/26) |
| Ligue 1 / Ligue 2 | France | 1–2 | planned |
| Eredivisie | Netherlands | 1 | JSON ready (25/26) |
| Süper Lig | Turkey | 1 | JSON ready (25/26) |
| SuperLiga | Romania | 1 | JSON ready (25/26) |
| Czech First League | Czechia | 1 | JSON ready (25/26) |
| Austrian Football Bundesliga | Austria | 1 | JSON ready (25/26) |
| Swiss Super League | Switzerland | 1 | JSON ready (25/26) |
| Scottish Premiership | Scotland | 1 | planned |
| Belgian Pro League | Belgium | 1 | JSON ready (25/26) |
| Danish Superliga | Denmark | 1 | JSON ready (25/26) |
| Super League Greece 1 | Greece | 1 | JSON ready (25/26) |
| HNL | Croatia | 1 | JSON ready (25/26) |
| Cypriot First Division | Cyprus | 1 | JSON ready (25/26) |
| Serbian SuperLiga | Serbia | 1 | JSON ready (25/26) |
| Nemzeti Bajnokság I | Hungary | 1 | JSON ready (25/26) |
| First Professional Football League | Bulgaria | 1 | JSON ready (25/26) |
| Slovak Super Liga | Slovakia | 1 | JSON ready (25/26) |
| Prva liga | Slovenia | 1 | JSON ready (25/26) |
| League of Ireland Premier Division | Ireland | 1 | JSON ready (2025) |

Do not skip Phase 1 stabilization (DB field limits ✓, JS modularization, N+1 fixes) before expanding to multi-league.

## Known Transfermarkt XPath patterns (verified)
- German clubs: @title = "German Champion"
- Italian clubs: @title = "Italian Champion"
- French clubs: @title = "French Champion"
- Portuguese clubs: @title = "Portugese Champion"  ← TM typo, do not correct
- Swedish clubs: @title = "Swedish Champion"
- Polish clubs: @title = "Polish Champion"
- Norwegian clubs: @title = "Norwegian Champion"
- Dutch clubs: @title = "Dutch Champion"
- English clubs: @title = "English Champion"
- Spanish clubs: @title = "Spanish Champion"
- Turkish clubs: @title = "Turkish Champion"
- Scottish clubs: @title = "Scottish Champion"
- Belgian clubs: @title = "Belgian Champion"
- Romanian clubs: @title = "Romanian Champion"
- Czech clubs: @title = "Czech Champion"
- Austrian clubs: @title = "Austrian Champion"
- Swiss clubs: @title = "Swiss Champion"
- Danish clubs: @title = "Danish Champion"
- Greek clubs: @title = "Greek Champion"
- Croatian clubs: @title = "Croatian Champion"
- Cypriot clubs: @title = "Cypriot Champion"
- Serbian clubs: @title = "Serbian Champion"
- Hungarian clubs: @title = "Hungarian Champion"
- Bulgarian clubs: @title = "Bulgarian Champion"
- Slovak clubs: @title = "Slovak Champion"
- Slovenian clubs: @title = "Slovenian Champion"
- Irish clubs: @title = "Irish Champion"
- Moldovan clubs: @title = "Moldavian Champion"  ← TM uses "Moldavian" not "Moldovan"
- Ukrainian clubs: @title = "Ukrainian Champion"
- Bosnian clubs: @title = "Bosnian-Herzegovinian Champion"  ← TM uses full hyphenated form
- Macedonian clubs: @title = "Macedonian Champion"
- Albanian clubs: @title = "Albanian Champion"  ← unverified; TM may not track in header
- Latvian clubs: @title = "Latvian Champion"  ← unverified; TM may not track in header
- Lithuanian clubs: @title = "Lithuanian Champion"
- Estonian clubs: @title = "Estonian Champion"
- Icelandic clubs: @title = "Icelandic Champion"  ← unverified; TM may not track in header
- Finnish clubs: @title = "Finnish Champion"  ← unverified; TM may not track in header
- Montenegrin clubs: @title = "Montenegrian Champion"  ← TM uses "Montenegrian" (with extra 'i'), verified via static HTML
- Luxembourgish clubs: @title = "Luxembourgian Champion"  ← TM uses "Luxembourgian" (not "Luxembourgish"), verified via static HTML
- Maltese clubs: @title = "Maltese Champion"  ← unverified; TM may not track in header
- Welsh clubs: @title = "Welsh Champion"  ← unverified; TM may not track in header

## Data quality rules

- `average_attendance` must be NULL if not scraped — never 0 (`clean_int()` returns None for 0)
- Stadium coordinates fall back to Nominatim (OSM) when Wikipedia has no geo data — logged at WARNING
- If Nominatim also fails, set `"latitude"` and `"longitude"` directly in the stadium JSON entry as a hardcoded last resort (verified from OSM way ID or Google Maps). Example: `"latitude": 45.8813164, "longitude": 25.8083825`. Missing coords block map display — they are mandatory.
- `ownership` must never be UNKNOWN when `owner_raw` has a value — no public keyword match → PRIVATE
- JSON `stadium.owner_raw` fires only when Wikipedia infobox has no owner/operator row; it does not override Wikipedia data
- Stadium images must be non-null — `og:image` is the fallback if infobox image not found; images stored at full resolution (no `/thumb/` in URL)

## Regenerate derived artifacts after data changes
Two pre-rendered artifacts must be regenerated whenever the data they show changes, then
committed (they are served as static files, NOT rendered per request — Render 512 MB limit):
- `python manage.py generate_stadiums_json` → `static/data/stadiums_map.json` (operational map)
- `python manage.py generate_tournament_maps` → `static/exports/tournament_<slug>.png`
  (the back-end tournament maps embedded on each `/tournaments/<slug>/` page, with logo +
  watermark; re-run after any tournament-venue/bid change). Add `--slug <slug>` for one.

## Link & name validation (MANDATORY post-scrape QA)

The scraper has assigned wrong external IDs/pages — e.g. a German club's Transfermarkt
verein ID (and its crest) to a Maltese team, or a German stadium's name to a Maltese
ground. We must never send users to the wrong club/stadium. After **every** scrape, run
these two audits and resolve all findings before considering the data clean:

```bash
python -X utf8 manage.py audit_stadium_names            # stadium name vs its Wikipedia title
python -X utf8 manage.py audit_team_links --country <C> # team Transfermarkt link vs real club
python -X utf8 manage.py audit_stadium_names --fix      # adopt wiki titles for SUSPECT names
python -X utf8 manage.py audit_team_links --country <C> --fix  # clear wrong TM links + crests
```

**Detection rules (embed in the scrape itself, not just the audit):**
1. **Stadium name ↔ Wikipedia title.** If the scraped `name` shares ZERO significant
   tokens with its own Wikipedia page title, it's suspect. SPONSOR renames (both names
   fit the country, e.g. Signal Iduna Park = Westfalenstadion) are OK; a name in a
   language FOREIGN to the country (German "Stadion Rehberge" for Malta) is wrong → adopt
   the Wikipedia title.
2. **Team name ↔ Transfermarkt page title.** Fetch the TM page `<title>` (the real club
   name) and compare to the team name. Zero overlap ⇒ wrong verein ID; the crest
   (`tmssl …/wappen/<id>.png`) is wrong too → clear both. TM is fetchable with a desktop
   browser User-Agent.
3. **Comparison must transliterate AND substring-match** to avoid false positives:
   ð→d, þ→th, ø→o, æ→ae, ł→l, đ→d; and treat a token as matching if it is a
   substring/prefix of the other (so "Breiðablik"=="Breidablik", "KuPS Kuopio"~="Kuopion
   Palloseura", "Vaasa"~="Vaasan", "Grobiņas"~="Grobina" are NOT flagged).
4. **Fix direction = trust the field that matches the country/coords.** Usually the
   Wikipedia URL/title is right and the name/TM-ID is wrong; but the reverse happens
   (e.g. "Hybel Arena Horsens" had the right name but a Romanian wiki link + Bucharest
   coords). Don't blanket-overwrite — verify which side is consistent with the country.
5. **Run TM fetches SEQUENTIALLY** (concurrency triggers 429/502/504); the audit retries
   with backoff and treats HTTP 404 as a dead (wrong) link.

Production data corrections go in a **data migration** (see migrations 0057–0059), since
`build.sh` does not `loaddata`.

## Ownership integrity contract (NON-NEGOTIABLE)

Ownership is factual, legal information. Publishing incorrect ownership damages the credibility of the entire project. These rules are binding:

**Two-source verification is mandatory on every scrape:**
1. Wikipedia infobox `owner` / `operator` row  (primary — free-text, most specific)
2. Wikidata `P127` (owned by) property         (secondary — structured, cross-check)
3. JSON `stadium.owner_raw`                     (manual override for gaps in both above)

**Decision rules:**
- Both sources agree → use Wikipedia (more specific text), log INFO
- Sources conflict → log WARNING with both values, use Wikipedia (more specific), flag for human review
- Only one source → use it, log INFO that second source was absent
- No source at all → `UNKNOWN`, log WARNING — this is the ONLY valid use of UNKNOWN

**Strictly forbidden:**
- Guessing ownership from team name (e.g. "FC Bayern" does not mean Bayern owns the stadium)
- Inferring ownership from city name without an infobox/Wikidata entry
- Silently defaulting to PRIVATE or PUBLIC without a source value
- Publishing UNKNOWN when any source has data

**After every scrape, grep the log for `[Ownership CONFLICT]` and `[Ownership UNKNOWN]` and resolve manually before considering the data clean.**

## Scraper data files (`scripts/data/urls_*.json`)

Ownership merge priority: **Wikipedia infobox owner → JSON `stadium.owner_raw` → UNKNOWN**

Set `owner_raw` in JSON for stadiums where Wikipedia has no owner infobox row:
```json
"stadium": { "owner_raw": "Município de Braga", ... }
```

Public keywords cover ~15 European language families:

| Language(s) | Sample keywords |
|-------------|----------------|
| English | `city of`, `municipality`, `council`, `town of`, `agglomeration`, `ministry`, `government` |
| Italian | `comune di`, `comunale`, `provincia`, `città metropolitana`, `sport e salute` |
| German (DE/AT/CH) | `stadt `, `gemeinde`, `landkreis`, `freie und hansestadt`, `bezirksamt`, `land ` (Austrian federal states: Land Salzburg, Land Tirol …) |
| French (FR/BE/CH) | `commune de`, `mairie`, `métropole`, `ville de`, `agglomération`, `communauté` |
| Spanish | `ayuntamiento`, `municipio`, `diputación`, `generalitat`, `junta de `, `concello ` (Galician city council), `cabildo ` (Canary Islands island council) |
| Portuguese | `município`, `câmara municipal`, `junta de freguesia`, `autarquia` |
| Polish | `miasto `, `miasto stołeczne`, `gmina `, `województwo`, `skarb państwa` |
| Dutch/Belgian | `gemeente `, `stad `, `provincie `, `gewest ` |
| Turkish | `belediye`, `büyükşehir`, `il özel idaresi`, `devlet`, `bakanlı` (ministry — covers bakanlık/bakanlığı) |
| Norwegian/Danish | `kommune`, `fylke`, `amt ` |
| Swedish | `stadsförvaltning`, `stadsfastigheter`, `landsting` |
| Finnish | `kaupunki`, `kunta ` |
| Czech/Slovak | `město `, `statutární město`, `obec `, `kraj `, `ministerstvo` |
| Romanian | `primăria`, `primărie`, `consiliu local`, `județ`, `municipiu`, `ministerul` |
| Croatian/Serbian/Bosnian | `grad `, `gradska `, `općina `, `skupština` |
| Slovenian | `mestna občina`, `občina `, `javni zavod` |
| Hungarian | `város `, `önkormányzat`, `fővárosi` |
| Greek (transliterated) | `dimos `, `dimou` |


## UI/UX conventions

### Navigation
- "← Map" back button lives in the sticky navbar via `{% block extra_nav %}` slot
  — never as a standalone element in the page body
- The navbar slot is filled only on detail pages (stadium_detail, team_detail, etc.)

### Stadium detail hero
- Full-width, 480px tall, object-fit: cover
- Gallery carousel if multiple images exist; single image fallback
- Stadium name overlaid on hero (bottom-left, white text, dark gradient)
- JS in static/js/stadium-detail-gallery.js — no inline scripts