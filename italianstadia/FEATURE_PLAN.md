# Feature Plan — Map Export (Static Image)
_Created: 2026-06-15 | Branch: main_

## Problem / Goal
Football social media pages and analysts want to export the filtered stadium
map as a professional static image (e.g. "all artificial turf venues in Europe")
for sharing on Twitter/X, Instagram, or Reddit. The export must look polished
out of the box for non-professionals, while giving enough configuration for
professional use. Server-side: MapTiler Static API for the base tile, Pillow
for all overlays (dots, labels, legend, north arrow, title).

## Scope
**In scope:**
- [ ] `GET /api/export/map/` → PNG download
- [ ] **Filter params** (what stadiums to show): `surface`, `country`, `league`, `ownership`
- [ ] **Size presets**: `twitter` 1500×500 · `instagram` 1080×1080 · `landscape` 1920×1080 (default)
- [ ] **Base map style**: `dark` (default) · `light` · `topo` · `satellite`
- [ ] **Dot colour scheme**: `surface` (default, yellow/green/grey by surface type) · `country` (one colour per country) · `single` (one colour, pass `dot_color=#hex`)
- [ ] **Legend overlay**: `legend=1` (default on) · `legend=0` — semi-transparent box, bottom-left
- [ ] **North arrow**: `north=1` (default off) · `north=0` — simple N + arrow, top-right
- [ ] **Title text**: `title=Artificial+Turf+in+Europe` (default off) — bold white text top-left with dark pill background
- [ ] **Label toggle**: `labels=1` (default on) · `labels=0` — show/hide stadium name labels
- [ ] Rate-limit: 1 export / 10 s per IP (Django cache)
- [ ] `MAPTILER_API_KEY` read from env var

**Out of scope:**
- Payment / Stripe gating (can be layered on later)
- Badge/logo images on the export
- Animated exports
- Existing `/api/export/stadiums/` CSV endpoint (untouched)
- Changes to the live map JS or templates

## Query parameter reference
| Param | Values | Default | Description |
|-------|--------|---------|-------------|
| `surface` | `GRASS`, `ARTIFICIAL`, `HYBRID` | — | Filter stadiums by surface |
| `country` | e.g. `Norway` | — | Filter by country |
| `league` | e.g. `Serie+A` | — | Filter by league |
| `ownership` | `PUBLIC`, `PRIVATE`, `MIXED` | — | Filter by ownership |
| `size` | `twitter`, `instagram`, `landscape` | `landscape` | Export dimensions |
| `style` | `dark`, `light`, `topo`, `satellite` | `dark` | Base map style |
| `color_by` | `surface`, `country`, `single` | `surface` | Dot colouring scheme |
| `dot_color` | `#rrggbb` | `#f5c542` | Used when `color_by=single` |
| `legend` | `0`, `1` | `1` | Show legend box |
| `north` | `0`, `1` | `0` | Show north arrow |
| `title` | URL-encoded string | — | Title overlay text |
| `labels` | `0`, `1` | `1` | Show stadium name labels |

## Export sizes
| Preset | W | H |
|--------|---|---|
| `twitter` | 1500 | 500 |
| `instagram` | 1080 | 1080 |
| `landscape` | 1920 | 1080 |

## MapTiler style mapping
| `style` param | MapTiler style ID |
|---------------|-------------------|
| `dark` | `dataviz-dark` |
| `light` | `dataviz` |
| `topo` | `topo-v2` |
| `satellite` | `satellite` |

MapTiler bbox static endpoint:
```
GET https://api.maptiler.com/maps/{style_id}/static/{lon_min},{lat_min},{lon_max},{lat_max}/{W}x{H}.png?key={KEY}
```

## Dot colour schemes
**`surface`** (default):
- `#f5c542` — Artificial
- `#4caf50` — Grass / Natural
- `#2196f3` — Hybrid
- `#888888` — Unknown

**`country`**: auto-assign from a fixed palette of 12 distinct colours cycling per unique country name.

**`single`**: use `dot_color` param hex value for all dots.

## Overlay rendering (Pillow, drawn in order)
1. Base PNG from MapTiler
2. Dots (radius 6px, filled circle with 1px white border)
3. Labels (if `labels=1`): stadium name, white text, 2px dark outline, right/left of dot
4. Legend box (if `legend=1`): semi-transparent dark pill, bottom-left, lists colour → meaning
5. North arrow (if `north=1`): simple filled triangle + "N" text, top-right corner
6. Title bar (if `title` provided): bold white text on dark rounded-rect, top-left

## Files that will change
| File | Change type | Why |
|------|-------------|-----|
| `italianstadia/settings.py` | Edit | Add `MAPTILER_API_KEY` env read |
| `italiastadiaapp/views.py` | Edit | Add `map_export` view + helper functions |
| `italiastadiaapp/urls.py` | Edit | Register `/api/export/map/` |
| `requirements.txt` | Edit | Pin Pillow explicitly |
| `italiastadiaapp/tests/test_api.py` | Edit | Smoke tests |

## Implementation steps
1. [ ] Add `MAPTILER_API_KEY` to `settings.py`
2. [ ] Write helper: `_parse_export_params(request)` → validated dict of all params
3. [ ] Write helper: `_get_export_stadiums(params)` → filtered queryset → list of dicts
4. [ ] Write helper: `_fetch_maptiler_tile(bbox, style, W, H)` → PIL Image
5. [ ] Write helper: `_draw_dots(img, stadiums, params, bbox, W, H)` → PIL Image
6. [ ] Write helper: `_draw_labels(img, stadiums, params, bbox, W, H)` → PIL Image
7. [ ] Write helper: `_draw_legend(img, params, stadiums)` → PIL Image
8. [ ] Write helper: `_draw_north_arrow(img, W, H)` → PIL Image
9. [ ] Write helper: `_draw_title(img, title_text, W)` → PIL Image
10. [ ] Assemble `map_export` view calling helpers in order → `HttpResponse(png, content_type="image/png")`
11. [ ] Add URL in `urls.py`
12. [ ] Pin Pillow in `requirements.txt`
13. [ ] Add smoke tests
14. [ ] Add `MAPTILER_API_KEY` to Render env + sign up at maptiler.com (manual)

## Test plan
- `test_map_export_returns_png` — GET with no params → 200, content-type image/png
- `test_map_export_surface_filter` — `?surface=ARTIFICIAL` → 200, PNG
- `test_map_export_no_results` — filter with no matches → 400 with JSON error
- Manual: `curl "http://localhost:8000/api/export/map/?surface=ARTIFICIAL&size=twitter&style=dark&legend=1&north=1&title=Artificial+Turf+in+Europe" -o out.png && start out.png`

## Rollback plan
- Remove `map_export` from `views.py` and its URL from `urls.py`
- No migration needed
