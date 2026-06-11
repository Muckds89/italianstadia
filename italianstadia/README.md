# Stadiums of Europe

An interactive web map and data dashboard for football stadiums across Europe. Browse operational stadiums, explore planned developments, filter by country and league, and drill into stadium, team, and city detail pages.

**Live:** https://italianstadia-2.onrender.com

---

## Features

- **Interactive Leaflet map** with two modes: operational stadiums and under-development projects
- **Badge markers** showing team crests; hover tooltips with stadium name and capacity
- **Filters** by country, league, ownership type, and stadium tier
- **Search** with live autocomplete (mode-aware: operational or development)
- **Stadium detail pages** — hero image, location mini-map, team info, capacity, ownership
- **Team detail pages** — badge, league, stadium link, key stats
- **City detail pages** — population, teams, linked stadiums
- **Sortable list views** for stadiums, teams, and cities
- **Data export API** — download operational stadium data as JSON or CSV with optional filters
- **Automated season refresh** — weekly cron job on Render updates squad/league data
- **Privacy policy page** — GDPR-aligned, required for AdSense
- **PWA-ready** — web app manifest included

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 5.1, Python 3.13 |
| Database | SQLite (dev) · PostgreSQL (prod via `dj_database_url`) |
| Frontend | Leaflet.js, Bootstrap 5, vanilla JS |
| Deployment | Render (web service + weekly cron job) |
| Static files | WhiteNoise with compression |
| Data sources | Wikipedia, Transfermarkt |

---

## Project structure

```
italianstadia/          Django project config (settings, root urls, wsgi)
italiastadiaapp/        Single Django application
  models.py             City, Stadium, Team, StadiumDevelopment, LastRefresh, Country, League
  views.py              Page views + GeoJSON API endpoints + data export API
  urls.py               All URL patterns (namespace: italiastadiaapp)
  admin.py              Admin configuration
  context_processors.py Injects AdSense vars into all templates
  templates/            HTML templates (APP_DIRS = True)
    index.html              Map dashboard
    base_detail.html        Shared base for all detail/list pages
    stadium_detail.html
    stadium_list.html
    team_detail.html
    team_list.html
    city_list.html
    stadium_development_detail.html
    privacy.html
    adsense_unit.html       Reusable ad unit partial
  static/
    js/
      map.js                    Leaflet map, markers, filters, search, popups
      stadium-detail-map.js     Mini-map on stadium detail pages
    css/styles.css
  tests/
    test_api.py
    test_models.py
    test_views.py
  fixtures/
    initial_data.json       Full production dataset (loaded on deploy)
  management/commands/
    update_all_leagues.py   Orchestrator: scrape all leagues + update UEFA rankings
    scrape_season.py        Single-league Transfermarkt scraper
    update_uefa_ranking.py
    update_club_coefficients.py
scripts/                Standalone data population scripts
  populate_data_from_transfermrkt.py
  data/                 urls_*.json files — one per league
render.yaml             Render services config (web + cron)
build.sh                Render build: install → collectstatic → migrate → loaddata
```

---

## Data model

```
Country (name, code ISO-2)
  └── League (name, country FK, division_level)

City (name, population, country, wikipedia_url, image_url)
  └── Stadium (name, capacity, city FK, latitude, longitude,
               ownership [PUBLIC/PRIVATE/MIXED/UNKNOWN], owner_raw,
               year_of_construction, wikipedia_url, image_url)
        └── Team (name, tier, league FK, stadium FK, city FK,
                  average_attendance, image_url, wikipedia_url, transfermarkt_url,
                  under_development_stadium FK → StadiumDevelopment)

StadiumDevelopment (name, project_type, status, future_capacity,
                    estimated_opening, latitude, longitude,
                    architect, developer, source_url, image_url)

LastRefresh (pk=1 singleton — tracks last automated scrape run)
```

---

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/stadiums/` | GeoJSON FeatureCollection of all operational stadiums |
| `GET /api/stadium-developments/` | GeoJSON FeatureCollection of planned/under-construction stadiums |
| `GET /api/export/stadiums/` | Export operational stadiums as JSON or CSV |
| `GET /api/status/` | Stadium count + last automated refresh status |

### Export API query parameters

`GET /api/export/stadiums/?format=csv&country=Italy&league=Serie+A&ownership=PUBLIC`

| Param | Example | Description |
|-------|---------|-------------|
| `format` | `json` (default) or `csv` | Response format |
| `country` | `Italy` | Filter by country name |
| `league` | `Serie A` | Filter by league name |
| `ownership` | `PUBLIC` | Filter by ownership type |

---

## Running locally

```bash
# 1. Clone and create virtual environment
python -m venv my_django_env
my_django_env\Scripts\activate          # Windows
# source my_django_env/bin/activate     # macOS/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Apply migrations and load data
python manage.py migrate
python manage.py loaddata italiastadiaapp/fixtures/initial_data.json

# 4. Run the dev server
python manage.py runserver
```

Open http://127.0.0.1:8000

---

## Common commands

```bash
# Run all tests
pytest

# Run only API tests
pytest italiastadiaapp/tests/test_api.py -v

# Create and apply migrations after model changes
python manage.py makemigrations
python manage.py migrate

# Collect static files
python manage.py collectstatic --noinput

# Validate Wikipedia URLs before scraping a league
python -X utf8 scripts/validate_wiki_urls.py scripts/data/urls_<league>.json --skip-cities

# Scrape a single league
python manage.py scrape_season --league serie-a

# Refresh all leagues (runs on Render every Monday 05:00 UTC)
python manage.py update_all_leagues
```

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Production | Django secret key |
| `DATABASE_URL` | Production | PostgreSQL connection string (activates Postgres) |
| `DEBUG` | Optional | Set to `False` in production (default: `True`) |
| `GOOGLE_ADSENSE_CLIENT` | Optional | AdSense publisher ID (`ca-pub-...`) — ads hidden if unset |
| `GOOGLE_ADSENSE_SLOT` | Optional | AdSense ad unit slot ID — ads hidden if unset |

---

## Deployment (Render)

Deployment is configured in `render.yaml`:

- **Web service** — runs `gunicorn italianstadia.wsgi:application`; `build.sh` handles install, collectstatic, migrate, and loaddata on every deploy
- **Cron job** — runs `python manage.py update_all_leagues` every Monday at 05:00 UTC; records result in the `LastRefresh` table (visible at `/api/status/`)

Both services share the `italianstadia-env` environment variable group in the Render dashboard.

---

## League coverage

Currently live: **Serie A, Serie B, Serie C** (Italy — full coverage).

Scrapers ready for: Premier League, Championship, Bundesliga, La Liga, Ligue 1, Eredivisie, Primeira Liga, Ekstraklasa, Süper Lig, and 15+ more European leagues. See `scripts/data/` for the full list of prepared `urls_*.json` files.

---

## License

Data sourced from Wikipedia (CC BY-SA) and Transfermarkt. Project code is provided for educational purposes.
