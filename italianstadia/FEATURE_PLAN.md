# Feature Plan — Sprint 6: AdSense · Data Export API · Season Refresh Pipeline
_Created: 2026-06-11 | Branch: feature/sprint-6_

---

## Problem / Goal

Three independent revenue / automation improvements:

1. **AdSense**: The site has no monetisation. Adding Google AdSense banner units to detail and list pages generates passive revenue without disrupting the map (which stays ad-free to preserve UX).

2. **Data Export API**: Power users (scouts, journalists, data analysts) want to download the stadium dataset as CSV or JSON for offline analysis. A public `/api/export/stadiums/` endpoint with format + filter params fills this gap and is a future monetisation hook.

3. **Season Refresh Pipeline**: `update_all_leagues` already exists as a management command but runs only when triggered manually. Wiring it to a Render Cron Job automates weekly data freshness with zero developer effort. A `LastRefresh` model tracks the last run timestamp and status.

Success = ads visible on detail/list pages, CSV/JSON download working with filters, and a `render.yaml` cron service that runs the full scrape on a weekly schedule.

---

## Scope

**In scope:**
- [ ] AdSense: `<script async>` in `<head>` of `base_detail.html`, `stadium_list.html`, `team_list.html`, `city_list.html` — guarded by `GOOGLE_ADSENSE_CLIENT` env var (empty → no script, no ad slots rendered)
- [ ] AdSense: one responsive display ad unit per page in a clearly defined slot (below header, not intrusive)
- [ ] AdSense: `index.html` (map) receives **NO ads** — full-viewport map UX must stay clean
- [ ] Export API: `GET /api/export/stadiums/` — params `format` (csv|json), `country`, `league`, `ownership`; returns CSV attachment or JSON array
- [ ] Export API: URL registered in `urls.py`, view in `views.py`, one test covering CSV + JSON + filter + invalid format
- [ ] Season pipeline: `render.yaml` defining a cron service that runs `update_all_leagues` every Monday at 05:00 UTC
- [ ] Season pipeline: `LastRefresh` model (single-row upsert) + admin registration; updated by `update_all_leagues` on success and failure
- [ ] Status endpoint: `GET /api/status/` returns JSON with `stadium_count`, `last_refresh`, `last_refresh_status`

**Out of scope (do not touch):**
- Payment / subscription gating on the export endpoint
- Celery / Redis task queue
- Ad placement on the map page (`index.html`)
- Changing existing scraper logic or data models other than adding `LastRefresh`
- AdSense auto-ads (manual placement only — keeps layout predictable)

---

## Design decisions

1. **AdSense publisher ID via env var `GOOGLE_ADSENSE_CLIENT`** | Alternative: hardcoded | Reason: different IDs for staging vs prod; empty string → template guard hides all ads
2. **Export as a plain Django view, no DRF** | Alternative: DRF ViewSet | Reason: single endpoint; `csv` module + `json.dumps` is sufficient; avoids adding a dependency
3. **`LastRefresh` is a single-row model (upsert on pk=1)** | Alternative: append-only log | Reason: only latest status matters for the `/api/status/` endpoint; simpler to display
4. **Render Cron Job via `render.yaml`** | Alternative: GitHub Actions schedule | Reason: Render already hosts the app; the cron service inherits the same env group and DB URL automatically
5. **Export endpoint is public** | Alternative: API key auth | Reason: adds friction with no revenue benefit yet; can add Django `ratelimit` in a future sprint

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/models.py` | Edit | Add `LastRefresh` model |
| `italiastadiaapp/migrations/` | New | Migration for `LastRefresh` |
| `italiastadiaapp/admin.py` | Edit | Register `LastRefresh` |
| `italiastadiaapp/views.py` | Edit | Add `export_stadiums` + `api_status` views |
| `italiastadiaapp/urls.py` | Edit | Register `/api/export/stadiums/` and `/api/status/` |
| `italiastadiaapp/management/commands/update_all_leagues.py` | Edit | Upsert `LastRefresh` after run |
| `italiastadiaapp/templates/base_detail.html` | Edit | AdSense `<script>` in `<head>` + ad unit block |
| `italiastadiaapp/templates/stadium_list.html` | Edit | AdSense `<script>` + ad unit after `<h1>` |
| `italiastadiaapp/templates/team_list.html` | Edit | AdSense `<script>` + ad unit after `<h1>` |
| `italiastadiaapp/templates/city_list.html` | Edit | AdSense `<script>` + ad unit after `<h1>` |
| `italiastadiaapp/tests/test_api.py` | Edit | Export + status endpoint tests |
| `italianstadia/settings.py` | Edit | Read `GOOGLE_ADSENSE_CLIENT` from env |
| `render.yaml` | New | Cron service definition |

---

## Implementation steps (bottom-up order)

1. [ ] **Model**: add `LastRefresh` to `models.py`; run `makemigrations`
2. [ ] **Admin**: register `LastRefresh` in `admin.py`
3. [ ] **update_all_leagues**: wrap `handle()` in try/except; upsert `LastRefresh(pk=1)` on both success and exception
4. [ ] **Settings**: `GOOGLE_ADSENSE_CLIENT = os.environ.get("GOOGLE_ADSENSE_CLIENT", "")`
5. [ ] **Export view**: `export_stadiums(request)` — parse params, query with `select_related("city").prefetch_related("teams__league")`, stream CSV or JSON
6. [ ] **Status view**: `api_status(request)` — return JSON with stadium count, last refresh info
7. [ ] **URLs**: add both endpoints to `urls.py`
8. [ ] **AdSense templates**: add `<script async>` to `<head>` + one `<ins class="adsbygoogle">` unit guarded by `{% if adsense_client %}`; pass `adsense_client` from each view
9. [ ] **render.yaml**: define web service (mirrors existing `build.sh` config) + cron service
10. [ ] **Tests**: CSV headers, JSON array, country filter, invalid format → 400, status endpoint

---

## PostgreSQL safety check

- [x] `LastRefresh` uses `DateTimeField`, `CharField(max_length=20)` for status — no truncation risk
- [x] No new `CharField` on `Stadium` — export reads existing fields only
- [x] No existing columns altered

---

## Export API contract

```
GET /api/export/stadiums/?format=csv&country=Italy&ownership=PUBLIC
```

| Param | Values | Default |
|-------|--------|---------|
| `format` | `csv`, `json` | `json` |
| `country` | country name string | all |
| `league` | league name string | all |
| `ownership` | `PUBLIC`, `PRIVATE`, `MIXED` | all |

**CSV columns:** `id, name, city, country, league, capacity, ownership, owner_raw, latitude, longitude, year_of_construction, wikipedia_url`

**JSON:** flat array of objects with the same keys (not GeoJSON).

**CSV response headers:** `Content-Type: text/csv`, `Content-Disposition: attachment; filename="stadiums.csv"`

**Error:** `400 {"error": "Invalid format. Use csv or json."}` for unknown format param.

---

## render.yaml cron service

```yaml
services:
  - type: web
    name: italianstadia
    env: python
    buildCommand: ./build.sh
    startCommand: gunicorn italianstadia.wsgi:application
    envVarGroups:
      - italianstadia-env

  - type: cron
    name: season-refresh
    env: python
    schedule: "0 5 * * 1"
    buildCommand: pip install -r requirements.txt
    startCommand: python manage.py update_all_leagues
    envVarGroups:
      - italianstadia-env
```

---

## AdSense ad unit placement

| Template | Unit position |
|----------|---------------|
| `base_detail.html` | Inside `{% block content %}` preamble — one unit just below the page hero / above the stats section; child templates can override with `{% block ad_slot %}` |
| `stadium_list.html` | Below the `<h1>` title, above the first league section |
| `team_list.html` | Below the `<h1>` title, above the first league section |
| `city_list.html` | Below the `<h1>` title |

Each unit is wrapped in `{% if adsense_client %}...{% endif %}` — no empty `<ins>` tags rendered when `GOOGLE_ADSENSE_CLIENT` is unset.

---

## Test plan

- `test_csv_download` — GET `/api/export/stadiums/?format=csv` → 200, `Content-Type: text/csv`, first line is CSV header row
- `test_json_download` — GET `/api/export/stadiums/?format=json` → 200, response is a JSON list, first item has `id` and `name`
- `test_country_filter` — `?format=json&country=Italy` → all items have `country == "Italy"`
- `test_invalid_format` — `?format=xlsx` → 400
- `test_status_endpoint` — GET `/api/status/` → 200, body contains `stadium_count`

---

## Rollback plan

- **AdSense**: set `GOOGLE_ADSENSE_CLIENT=""` in Render env → all ad units hidden via template guard; no code change needed
- **Export API**: remove the two `path()` entries from `urls.py`; existing routes unaffected
- **Season pipeline**: delete the cron service in Render dashboard; `LastRefresh` model stays but is harmless
