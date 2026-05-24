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
build.sh                ← Render deploy: pip install + collectstatic + migrate + loaddata
```

## Data model

```
City (name, population, country, wikipedia_url, image_url, description)
  └── Stadium (name, capacity, address, year_of_construction, latitude, longitude,
               ownership[PUBLIC/PRIVATE/MIXED/UNKNOWN], owner_raw,
               wikipedia_url, transfermarkt_url, image_url, description)
        └── Team (name, tier[1=A/2=B/3=C], girone[A/B/C], founded, manager,
                  num_of_titles, average_attendance, stadium FK, city FK,
                  wikipedia_url, transfermarkt_url, image_url,
                  under_development_stadium FK → StadiumDevelopment)
StadiumDevelopment (name, project_type[NEW/REDEVELOPMENT/EXPANSION],
                    status[PLANNING/APPROVED/UNDER_CONSTRUCTION/ON_HOLD/COMPLETED],
                    future_capacity, estimated_opening, latitude, longitude,
                    architect, developer, source_url, notes, image_url,
                    stadium FK → existing Stadium if redevelopment)
```

Stadium `tier` filtering is derived from the teams that play there — `stadium_list` view groups stadiums by `{team.tier for team in stadium.teams.all()}`.

## GeoJSON endpoints

- `GET /api/stadiums/` → `stadiums_geojson` — FeatureCollection with teams array in `properties`
- `GET /api/stadium-developments/` → `stadium_developments_geojson` — FeatureCollection for planned/under-construction stadiums

Both endpoints return `[longitude, latitude]` coordinates (GeoJSON standard). The `stadiums_geojson` view already uses `select_related("city").prefetch_related("teams")`.

## Frontend (map.js)

All filter state and map logic lives in `map.js` as a single file. Filter DOM elements are grabbed at top-level; the map supports two modes: `"operational"` (default, shows Stadium markers) and `"development"` (shows StadiumDevelopment markers). `currentLayerMode` tracks this. The map fetches GeoJSON via `fetch()` from the URL stored in `data-url` attributes on DOM elements in the template.

## Database setup

- **Local dev:** SQLite (auto, no config needed). `db.sqlite3` is in repo root.
- **Production:** `DATABASE_URL` env var activates PostgreSQL via `dj_database_url`. SSL is required when `DATABASE_URL` is set.
- No docker-compose. Just set `DATABASE_URL` in `.env` to use a local Postgres instead of SQLite.

## Critical constraints

**Field limits — existing models have violations** (`CharField(max_length=100)` on scraped names). When adding new fields or models:
```python
name = models.CharField(max_length=255)      # not 100
url = models.URLField(max_length=1000)       # already used in image_url — keep consistent
coordinates = models.FloatField()            # current pattern (not DecimalField)
capacity = models.IntegerField()             # not SmallIntegerField
```

**N+1 prevention** — `stadium_list` and `team_list` already use `select_related` + `prefetch_related`. Keep this pattern; `stadiums_json` view (`/api/stadiums-json/` — unused) does not and should be fixed or removed.

**Template lookup** — `APP_DIRS=True` and `DIRS=[]`, so templates must be in `italiastadiaapp/templates/`. The `index` view renders `"index.html"` (not `"italiastadiaapp/index.html"`). All other views do the same — no subdirectory prefix.

**URL reversal in tests** — All URL names must use the `italiastadiaapp` namespace: `reverse("italiastadiaapp:stadiums_geojson")`. Even though the root urlconf uses `include('italiastadiaapp.urls')` without an explicit namespace kwarg, Django still applies the `app_name` from the included module as the namespace — bare names like `reverse("stadiums_geojson")` will raise `NoReverseMatch`.

## Roadmap context

The project is currently Italy-only (Serie A/B/C). Planned expansions in `italianstadia_ROADMAP.md`:
- Phase 2: Add `Country`, `League`, `TeamSeasonRecord` models for multi-league Europe
- Phase 3: Historical season filtering
- Phase 4: Mobile-first UI, PWA
- Phase 5: Stadium depth (timelines, search, rankings)

Do not skip Phase 1 stabilization tasks (DB field limits, JS modularization, N+1 fixes) before expanding to multi-league.
