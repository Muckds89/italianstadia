# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

Interactive web map of European football stadiums, live at **stadiumsofeurope.com**.
Django 5.1 + SQLite (dev) / PostgreSQL (prod) + Leaflet.js + Bootstrap 5, deployed on
Render's free tier (512 MB — see "Memory budget" below, it shapes several designs).

Scale as of August 2026: **53 countries, 100 leagues, ~1,070 clubs, ~1,030 stadiums.**
The repo name and the `italianstadia` package are historical — this stopped being an
Italy-only project long ago; do not take either as a statement of scope.

Beyond the map it sells PNG map exports (€0.50 via Stripe), publishes insight pages, and
serves a public read-only data API.

**Do not write "currently" facts into this file.** Counts, coverage and roadmap status go
stale silently and are then read with the same authority as the rules that are still true.
This file is for rules and reasons; the code and the database are for state.

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
build.sh                ← Render deploy: pip install + migrate + loaddata + collectstatic
                          # Prod data is SYNCED FROM THE FIXTURE on every deploy:
                          # `loaddata initial_data` (upsert by PK, idempotent). Scraped
                          # league data lives only in local SQLite and reaches prod ONLY
                          # via this fixture. WORKFLOW after any data change (scrape, fix):
                          #   1. python -X utf8 manage.py dumpdata italiastadiaapp \
                          #        --exclude italiastadiaapp.exporttoken \
                          #        --exclude italiastadiaapp.lastrefresh \
                          #        --indent 2 -o italiastadiaapp/fixtures/initial_data.json
                          #      (-X utf8 is REQUIRED on Windows — without it dumpdata's
                          #       -o writes with cp1252 and dies on names like 'ț'/'ș',
                          #       leaving a corrupt fixture.)
                          #   2. python -X utf8 manage.py generate_stadiums_json   (static map)
                          #   3. commit both, then deploy.
                          # Prefer fixing data LOCALLY + re-dumping over write-only data
                          # migrations now that loaddata is the source of truth on deploy.
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

URLs come from `data-url` attributes on the `#map` element, never hardcoded in JS. Keep it
that way — the template is the only place that knows a URL.

**The two map layers load from DIFFERENT places, deliberately:**

```
data-stadiums-url     → {% static 'data/stadiums_map.json' %}   PRE-BUILT FILE (WhiteNoise)
data-developments-url → {% url '...stadium_developments_geojson' %}   LIVE ENDPOINT
```

The ~1,000 operational stadiums are a pre-generated file; querying them per request was
OOM-killing the dyno. The few dozen development projects are cheap, so they stay live.
`/api/stadiums/` still exists and is still correct, but the site itself does not use it —
it is there for external consumers. Do not "tidy" the map onto it.

## Database setup

- **Local dev:** SQLite (auto, no config needed). `db.sqlite3` is in repo root.
- **Production:** `DATABASE_URL` env var activates PostgreSQL via `dj_database_url`. SSL is required when `DATABASE_URL` is set.
- No docker-compose. Just set `DATABASE_URL` in `.env` to use a local Postgres instead of SQLite.

## Memory budget (Render free tier, 512 MB)

This single constraint explains several designs that otherwise look like over-engineering.
Before adding anything that runs per request, ask what it costs at 1,000 stadiums.

- **Pre-generate, commit, serve statically.** `stadiums_map.json`, `city_clubs.json`, the
  tournament and insight PNGs, and all ~1,060 crests are built by management commands and
  served by WhiteNoise. None of them touch the DB or PIL at request time.
- **`_RENDER_LOCK`** serialises map exports — one render at a time per worker. A second
  concurrent request gets a friendly 429 rather than stacking memory into an OOM 502.
- **FHD and 4K previews are downgraded to HD** in `map_export`. The paid path caps 4K too.
- **Tiles cache to /tmp, never to Django's LocMemCache** — holding tile bytes in RAM grows
  the worker render after render.
- Anything that would need a second full compose per request (e.g. a separate endpoint for
  export label geometry) must instead ride along on the render that already happened.

## Export renderer must be resolution-independent

The paid download differs from the free preview by the logo and the watermark, and by
NOTHING else. The preview is always HD; the file someone paid for may be FHD or 4K, so any
metric written in absolute pixels silently changes the layout between what they saw and
what they bought.

`_compose_export_image` scales `label_size` and `badge_size` by `W / _REFERENCE_W` (1280).
Everything else inside the renderer must scale the same way. Bugs already found and fixed:

- the inset's "Detail view" header reserved `int(IW*0.03) + 16` — that absolute 16 made the
  strip 16.9% of the box at HD but 13.8% at FHD;
- pill padding, row gap and the font-shrink STEP were fixed pixel counts, so HD and FHD
  settled on different font ratios;
- hand-placed inset labels are stored as FRACTIONS of the inset box, and clamped against
  fractions — never against the pill's own width or height, which is itself
  resolution-dependent because font sizes are integers.

When touching the renderer, place the same element at HD, FHD and 4K and compare the
resulting fractions. It is the only reliable check.

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

### Auto-slug constraint (Stadium, Team, and StadiumDevelopment)

`Stadium.slug`, `Team.slug`, and `StadiumDevelopment.slug` are all `unique=True` but not `null=True`. Each model's `save()` auto-generates the slug, so normal ORM usage (`create()`, `get_or_create()`, `save()`) is safe. **Never use `bulk_create()` on Stadium, Team, or StadiumDevelopment** — it bypasses `save()`, leaving slugs as `""`, and the second such row violates the `UNIQUE` constraint.

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
- Do not fetch a crest at render time — they are local files (see Crest sourcing)
- Do not write an absolute pixel size into the export renderer — scale it by `_REFERENCE_W`
- Do not delete a club that gets relegated out of a covered tier — move it to a hidden league
- Do not guess ownership, a coordinate, or a crest. Every one of them has a documented
  fallback chain, and every one ends in an explicit "unknown" rather than a plausible
  invention. A wrong fact that looks right is the worst outcome this project can produce
- Do not trust a filename, a club name or a league table to tell you what a badge shows.
  Look at the rendered image

## League coverage and the season update

Coverage is a fact about the DATABASE, not about this file — query it, never trust a table
here:

```bash
python -X utf8 manage.py season_status          # what is on which season
```

`League.season` is the source of truth ("2026/27", or "2026" for summer-season leagues:
the Nordics, Baltics, Ireland, Iceland, Georgia, Belarus). A league whose clubs you have
updated but whose `season` you forgot to bump is the easiest mistake to make here — the
map is right and every report about it is wrong.

**Updating a country for a new season** (the August job):
1. Get the new roster from that league's own `20xx–xx_<League>` Wikipedia article. Never
   infer promotions from last season's table — clubs get administratively relegated
   (Karviná, match-fixing), withdraw (Rukh Lviv), rename (Metalist 1925 → FC Kharkiv), or
   the whole division gets renamed (Championnat National → **Ligue 3**, 2026/27).
2. Diff against the DB, then move clubs between tiers rather than deleting and recreating.
3. Clubs relegated OUT of the covered tiers go to a hidden league — see below.
4. Create genuinely new clubs with Team + Stadium (+ City), sourcing crests via the
   infobox rule below and coordinates via the documented fallback chain.
5. Bump `League.season` on every tier you touched.
6. Assert the final roster against the article: count, no club missing or extra, and every
   club with a crest, a stadium and coordinates.
7. Regenerate derived artifacts, re-dump the fixture, run the tests.

### Hidden leagues hold relegated clubs

When a club drops out of the tiers we cover, do NOT delete it — that discards verified
stadium data you would have to re-scrape if it comes back up. Move it to a league one
level down with `hidden=True` (EFL League Two, Prva NL, Liga II, Regionalliga …).

Hidden means it is not offered in the export/league pickers, because a league containing
nothing but the three clubs that just went down renders a nonsense map. A lower tier that
is genuinely fully populated (Ligue 3, Serie C, EFL League One) is NOT hidden.

`Team.tier` must be kept in step with `League.division_level` — they are separate fields
and nothing enforces agreement.

### A league belongs to the country that RUNS it

`export_options` groups leagues by the country holding MOST of that league's grounds, not
by `League.country` and not by every country a ground sits in.

This is not pedantry. The New Saints are a Cymru Premier club who play at Park Hall in
**England**, and grouping by ground country put the entire Welsh league in England's
dropdown. Symmetrically, Cardiff/Swansea/Wrexham put the EFL Championship under Wales,
Vaduz put the Swiss Super League under Liechtenstein, Derry City put the League of Ireland
under Northern Ireland, and FC Andorra put the Segunda under Andorra.

Keys stay `city.country` free text because that is what the export filter matches on;
switching to the Country model's name breaks countries whose two spellings differ
("Czechia" vs "Czech Republic"). The counting query must NOT be `.distinct()` — collapsing
the rows makes every cross-border league a 1-1 tie and the fix silently does nothing.


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
- Belarusian clubs: @title = "Belarusian Champion"  ← unverified; TM may not track in header
- Russian clubs: @title = "Russian Champion"  ← unverified; TM may not track in header
- Azerbaijani clubs: @title = "Azerbaijani Champion"  ← unverified
- Armenian clubs: @title = "Armenian Champion"  ← unverified
- Kosovan clubs: @title = "Kosovan Champion"  ← unverified; TM may not track Kosovo
- Israeli clubs: @title = "Israeli Champion"  ← unverified
- Georgian clubs: @title = "Georgian Champion"  ← unverified

## Crest sourcing (SELF-HOSTED — never fetch a badge at render time)

Every club crest is a local PNG in `static/crests/<team-slug>.png`, recorded on
`Team.crest_file`, committed, and served by WhiteNoise. A map render makes **zero** network
calls for badges.

This is not an optimisation. Crests used to be pulled from Transfermarkt at render time;
TM soft-blocked us (HTTP 200 with a ZERO-BYTE body, so a status-code check called every
crest healthy) and 999 of 1,034 badges vanished. Wikimedia, the replacement, throttles
bursts. **Both failures are silent** — a missing crest draws a plain coloured dot, which
reads as a design choice rather than an error, and maps were published with bare dots
before anyone noticed.

```bash
python -X utf8 manage.py download_crests                 # fetch what is missing
python -X utf8 manage.py download_crests --league "X"
python -X utf8 manage.py refresh_dead_crests --fix       # re-source dead/wrong URLs
```

### Source order: the club article's INFOBOX first

1. **The `| image =` / `| logo =` parameter of the club's own Wikipedia article.** This is
   what the article itself renders, editors keep it current, and it is never absent the way
   Wikidata is.
2. Wikidata P154.
3. A scored scan of the article's images — last resort.

Wikidata P154 was the primary source and is simply MISSING for a lot of major clubs (Real
Madrid and Athletic Club both lack it), which pushed them onto the fallback scan and its
bug. Auditing 1,033 clubs against the infobox found 75 wrong crests.

### Two traps the scan must guard against

**MediaWiki returns an article's images in ALPHABETICAL order.** Taking the first keyword
match therefore selects a club's OLDEST badge, because clubs that document their crest
history have files named by year. "Athletic Club crest 1901.png" beat "Club Athletic Bilbao
logo.svg" sitting six entries later in the same list. Candidates are SCORED; position
decides nothing.

**A filename that dates itself is a retired badge** — `is_historic()`. A CLOSED range is
historic ("Anderlecht 1933–1959"); an OPEN one is the badge in use ("2015-heden", "2021-").
Ajax needs both: they readopted a 1928 badge in 2025 and the file records "1928-1991,
2025-". Also caught: "former logo", "old logo"/"old crest" (Newcastle and West Brom were
both on files that said so), centenary marks (Feyenoord's "100 years").

**A rebrand usually brings a new badge.** Sheffield Wednesday, Marseille, FC Kharkiv and
Aston Villa all had stale crests behind a name or identity change. Re-check the infobox
after any rename.

### Failure is recorded, not left blank

If neither the English nor the native-language Wikipedia has a crest, set `image_credit`
to a string starting **"No verified crest"**. `refresh_dead_crests` holds those clubs
rather than installing whatever it finds — without the guard it picked a golf-tournament
photo for Eintracht, graffiti for Górnik, a street photo for Middlesbrough and a
pronunciation recording (`De-FC_Augsburg.ogg`) for Augsburg.

### Verify crests by LOOKING at them

Filenames lie. After any crest change, render a contact sheet and inspect it — that is how
Marseille's stale badge and FC Kharkiv's pre-rebrand "M" were caught, and neither had a
suspicious filename. A quick sanity check that catches photographs: every real crest is
≥10% transparent pixels; the Di Stéfano photograph that shipped as Real Madrid's badge was
0.0%.

## Data quality rules

- `average_attendance` must be NULL if not scraped — never 0 (`clean_int()` returns None for 0)
- Stadium coordinate fallback chain: Wikipedia page geo markup → **Wikidata P625**
  (`fetch_wikidata_coordinates`, language-independent: resolves coords even when the
  linked English article has none but the native-language edition does, since both share
  one Wikidata item) → Nominatim (OSM) → JSON hardcoded `latitude`/`longitude`. Each step
  logged. A non-English `wikipedia_url` (e.g. `tr.`/`ru.wikipedia.org`) is fine and is the
  preferred fix when only the native page carries the data.
- If Nominatim also fails, set `"latitude"` and `"longitude"` directly in the stadium JSON entry as a hardcoded last resort (verified from OSM way ID or Google Maps). Example: `"latitude": 45.8813164, "longitude": 25.8083825`. Missing coords block map display — they are mandatory.
- `ownership` must never be UNKNOWN when `owner_raw` has a value — no public keyword match → PRIVATE
- JSON `stadium.owner_raw` fires only when Wikipedia infobox has no owner/operator row; it does not override Wikipedia data
- Stadium images must be non-null — `og:image` is the fallback if infobox image not found; images stored at full resolution (no `/thumb/` in URL)

## Regenerate derived artifacts after data changes

These are pre-built and committed, NOT rendered per request (see Memory budget). If you
change data and skip this, the site keeps serving the old version and nothing errors —
which is exactly why it needs a checklist rather than judgement.

**The full sequence after any data change:**

```bash
python -X utf8 manage.py download_crests          # only if clubs were added/renamed
python -X utf8 manage.py generate_stadiums_json
python -X utf8 manage.py generate_city_clubs --season "2026/2027"
python -X utf8 manage.py dumpdata italiastadiaapp \
    --exclude italiastadiaapp.exporttoken --exclude italiastadiaapp.lastrefresh \
    --indent 2 -o italiastadiaapp/fixtures/initial_data.json
python -X utf8 -m pytest -q
```

Regenerate the tournament and insight PNGs as well after any change to the RENDERER
itself, not just to the data — they bake the current renderer's metrics in.

Detail on each:
- `python manage.py generate_stadiums_json` → `static/data/stadiums_map.json` (operational map)
- `python manage.py generate_tournament_maps` → `static/exports/tournament_<slug>.png`
  (the back-end tournament maps embedded on each `/tournaments/<slug>/` page, with logo +
  watermark; re-run after any tournament-venue/bid change). Add `--slug <slug>` for one.
- `python manage.py generate_insight_maps` → `static/exports/insight_<key>.png`
  (insight hero maps, e.g. the national-team-only spotlight map; re-run when the underlying
  insight data changes — e.g. a new national-team-only ground).
- `python manage.py generate_city_clubs` → `static/data/city_clubs.json`
  (the clubs-per-city insight: cities with 2+ clubs, logos, tiers, coordinates). Cheap
  query-only pass; the `insight_city_clubs` view reads this file rather than aggregating
  per request. **Runs automatically in build.sh after `loaddata`** so prod refreshes on
  every deploy (data load); re-run locally after any scrape. Pass `--season "2026/2027"`
  on the August bulk update (default season lives in the command + `CURRENT_SEASON` in views).

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

**One consolidated link audit — run this after building OR scraping any `urls_*.json`:**

```bash
python -X utf8 scripts/_audit_club_wikis.py scripts/data/urls_<league>.json --tm
#   --quiet  print only the teams that have a problem
#   --tm     also HTTP-check Transfermarkt links (slower; omit for a quick wiki-only pass)
```

It checks, per team AND per stadium, and reports four states so nothing is silently
skipped:
- `MISSING` — the `wikipedia_url`/`transfermarkt_url` is empty (the scrape found nothing)
- `DEAD` / `DEAD-404` — the article / TM verein id does not exist
- `SUSPECT` — wrong KIND of page: a team link that is not a football-club article
  (falls back to the *city/region/concept* page — `Orenburg` city, `Karabakh` region,
  `Noah` the biblical figure, `Llapi River` — instead of `FC Orenburg`, `Qarabağ FK`,
  `FC Noah`, `KF Llapi`), or a stadium link that is not a venue article
- TM `BUSY-5xx` — transient 502/503/504 (TM under load), NOT a data error: the slug is
  cosmetic, the `verein/<id>` is canonical, and the scraper's `get_with_retry` handles it

Gotchas learned the hard way:
- Pass DECODED titles to the Wikipedia API (`urllib.parse.unquote` first) — sending the
  percent-encoded slug (`Fortuna_D%C3%BCsseldorf`) makes every accented club a false
  positive.
- Use the descriptive Wikipedia API UA `stadiamap/1.0 (email)` — the browser UA is blocked.
- A TM 502 is NOT caught by a wiki audit (different site) and is transient/slug-independent
  (the same id 502s on one slug and 200s on another, minute to minute). The fix is the
  scraper retry, not the slug — but prefer the ENGLISH TM slug for an English dataset
  (`lokomotiv-moscow`, not the German `lokomotiv-moskau`).

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

**Wikidata owners are classified by ENTITY TYPE, not by keyword.** P127 returns a
bare label — `Kortrijk`, `Lommel`, `Barcelona` — with no wording for the public
keyword list to match, so `classify_ownership` used to default every one to PRIVATE
and published municipally owned grounds as privately owned. `fetch_wikidata_ownership`
therefore also resolves each owner's **P31 (instance of)** and returns
`(label, kind)`; `_wd_kind_from_types` maps municipality/city/state/government →
PUBLIC and club/company → PRIVATE. The name alone cannot tell these apart —
"Barcelona" is the CLUB (Camp Nou is private), "Kortrijk" is the MUNICIPALITY
(Guldensporen is public). The type override applies **only** when Wikidata is the
sole source; Wikipedia's free text stays keyword-classified because it is more
specific. An unrecognised type returns `None` and changes nothing — never guess.

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

### Navigation parity (desktop ↔ mobile) — MANDATORY
`index.html` has TWO hand-built nav lists: a DESKTOP one (`d-none d-lg-flex`) and a
separate MOBILE dropdown (`d-lg-none`). They are NOT generated from a shared source, so
**any nav link you add, remove, or rename in one MUST be mirrored in the other** (both
carry a `SYNC RULE` HTML comment). The canonical link set is: Map, Stadiums
(Operational / Under Development), Teams, Cities, Insights, Export, Tournaments (all
tournament entries). Detail pages use `base_detail.html`, which has a SINGLE Bootstrap
`navbar-expand-lg` collapsing list (one source, auto-hamburger) — preferred pattern; just
keep its links aligned with index. After any nav edit, check the page at a narrow (<992px)
width to confirm the mobile menu shows the same items.

### Stadium detail hero
- Full-width, 480px tall, object-fit: cover
- Gallery carousel if multiple images exist; single image fallback
- Stadium name overlaid on hero (bottom-left, white text, dark gradient)
- JS in static/js/stadium-detail-gallery.js — no inline scripts