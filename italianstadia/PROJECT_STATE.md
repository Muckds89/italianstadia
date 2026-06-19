# PROJECT_STATE.md
_Last updated: 2026-06-19_

## What this is
**Stadiums of Europe** — Django 5.1 + Leaflet.js map dashboard of European football stadiums.
Live at: **https://www.stadiumsofeurope.com**
Hosted on: Render free tier (512 MB RAM limit — critical constraint)

---

## Architecture

```
italianstadia/         Django project config (settings, urls, wsgi)
italiastadiaapp/
  models.py            Country, League, City, Stadium, Team, StadiumDevelopment, ExportToken
  views.py             All views + export render pipeline (~2200 lines)
  urls.py              All URL patterns (namespace: italiastadiaapp)
  templates/
    index.html         Map dashboard (main entry point)
    export.html        Export configuration UI
    export_success.html  Post-payment download page
  static/
    js/map.js          Leaflet init, markers, filters, popups, export link sync
    css/styles.css
italianstadia/
  settings.py
render.yaml            Render Blueprint config (1 worker, 8 threads)
build.sh               Render deploy: pip install + migrate + collectstatic
requirements.txt
```

---

## Key Technical Decisions

### Export pipeline (`views.py`)
- **`_compose_export_image(params)`** — shared render core used by both preview and paid download
- **`_make_background()`** — memory-bounded CARTO tile fetch: pastes each 256×256 tile directly
  into W×H output (no giant stitch canvas). Peak RAM ≈ output image + 1 tile.
- **`_draw_dots_and_labels()`** — orthogonal (90°) polyline leader lines; side rule (left/right
  by map half); R3 clutter drop at ≥70 badges; R4 escalation (never drop) at <70 badges.
- **`_title_band_height()` / `_draw_title_in_band()`** — title rendered in reserved top band;
  map rendered in remaining `H - band` area so title never covers content.
- **`_draw_scale_bar()`** — real-world km from bbox centre latitude, bottom-centre.
- **`_RENDER_LOCK = BoundedSemaphore(1)`** — serialises renders within the process (OOM defence).
- **`/tmp` tile cache** — tiles cached to disk, persists across requests on same Render dyno.

### Stripe / payment flow
- `export_checkout()` → creates Stripe Checkout Session, stores params in metadata
- Webhook `checkout.session.completed` → creates `ExportToken` (one-time UUID)
- `export_success()` — hardened: DB-first token lookup, 3× retry on Stripe.retrieve(),
  recreate token from metadata as fallback (survives deploy restarts between payment and redirect)
- `_render_export_png()` — paid download endpoint, validates token, renders and serves PNG

### Gunicorn config (render.yaml + Render dashboard)
```
--workers 1 --threads 8 --timeout 60 --max-requests 120 --max-requests-jitter 20
```
**CRITICAL:** `render.yaml` only applies to Blueprint services. The Render dashboard
**Start Command** must be updated manually to match — these can drift.

### Filter auto-populate (map → export)
`map.js` `applyFilters()` updates `#exportNavLink` href with active filter params
so country/league/surface/ownership carry over when navigating to the export page.

---

## Non-Negotiable Rendering Rules (FEATURE_PLAN.md)

| Rule | Requirement |
|------|-------------|
| R1 | Base map = CARTO dark_all tiles (same as Leaflet). No Natural-Earth polygon fallback in normal renders. |
| R2 | Leader lines: 90° orthogonal polylines, never cross any badge, left-half→left label, right-half→right label |
| R3 | Drop unplaceable labels at ≥70 badges (no overlaps, keep centre clear) |
| R4 | At <70 badges, every label MUST display (3-tier escalation: clean → allow pill overlap → allow line clip; never drop) |

---

## Active Bugs / Pending Work

### FIXED: In-process Django cache OOM risk
Both `_fetch_one_tile()` and `_fetch_badge_image()` already use `/tmp` disk cache only — no
`cache.set()` with raw PNG bytes. Bug was pre-emptively fixed. Entry retained for history.

### Verify Render dashboard Start Command
Confirm the dashboard (not just `render.yaml`) has exactly:
```
gunicorn italianstadia.wsgi:application --workers 1 --threads 8 --timeout 60 --max-requests 120 --max-requests-jitter 20
```

### North Macedonia export
Needs a test run to confirm no OOM crash (bbox is tiny → was triggering tile upscale bug, now fixed).

---

## Recent Session Work (2026-06-15 to 2026-06-19)
- Rewrote `_make_background()` to memory-bounded tiling (eliminated 98MB stitch canvas OOM)
- Eliminated all `Image.new("RGBA", img.size)` + `alpha_composite` per-label allocations (was ~8MB × N)
- Implemented R2 orthogonal leader lines with `_route()` (H→V and V→H elbows, badge collision check)
- Implemented R4 3-tier escalation (verified: Greece 14/14, Serie A 18/18, England 67/67)
- Title/subtitle band — map renders in H_map area below reserved band, composited at end
- Added distance scale bar (`scale=1` param)
- Hardened `export_success` — DB-first lookup + 3× Stripe retry + metadata fallback
- Filter auto-populate: `map.js` updates export nav link href on every `applyFilters()` call
- Fixed export.html: autocomplete on focus, league filtered by country, white AC text,
  visible placeholders, prominent Generate Preview button, Distance scale bar checkbox
- Pinned gunicorn to `--workers 1` in `render.yaml`
- Added `_RENDER_LOCK` semaphore to prevent concurrent renders within the process
- Recovered 3 lost payments by hitting `export_success` with session_id directly

---

## ExportToken recovery (manual)
If a user pays but lands on an error, retrieve their token:
```bash
# On Render shell or local:
python manage.py shell
from italiastadiaapp.models import ExportToken
ExportToken.objects.filter(used=False).order_by('-created_at')[:5]
# Share the download URL: /export/download/<uuid>/
```

---

## Data model additions since initial build
- `ExportToken(token UUID, stripe_session_id, params JSON, used bool, created_at)`
- `Country`, `League` models added for multi-country support

## Roadmap (see CLAUDE.md for full list)
Currently: Italy (Serie A/B/C) + all European leagues scraped.
JSON files ready for 25+ leagues; just need scraper runs and data validation.
