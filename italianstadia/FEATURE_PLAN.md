# Feature Plan — Map Export (Static Image)
_Created: 2026-06-15 | Updated: 2026-06-15 | Branch: main_

## Problem / Goal
Football social media pages and analysts want to export the filtered stadium
map as a professional static image (e.g. "all artificial turf venues in Europe")
for sharing on Twitter/X, Instagram, or Reddit. The export must look polished
out of the box for non-professionals, while giving enough configuration for
professional use. Pillow renders all overlays (dots, labels, legend, north
arrow, title) on top of a base map.

---

## ⛔ RENDERING RULES (NON-NEGOTIABLE — apply to every export change)

These are permanent acceptance criteria. Any export render that violates them is
a regression, regardless of what else changed. Do not re-litigate these per task.

### R1 — Base map MUST match the live Leaflet map
- The static export's base map must be **visually the same tiles as the Leaflet
  map** the user sees on the site (CARTO **dark_all / dark_matter** for the dark
  style — see `map.js` tile layer URL as the single source of truth).
- The crude Natural-Earth country-polygon fallback (`_draw_countries`) is **only**
  an offline/OOM safety net — it must NOT be the normal preview/export output.
- Same projection, same tile source, same look. If the map looks "gross" / blocky
  compared to Leaflet, that is an R1 failure.
- Background-colour customisation tints **land only**, never the sea (sea keeps the
  tile/style base). A flat single-colour fill over the whole canvas is an R1 failure.

### R2 — Leader lines MUST avoid badges, and use 90° bends
- A label's leader line **must never cross any badge** (its own or another's).
- **Side rule:** badges on the **left half** of the map get their label on the
  **left**; badges on the **right half** get their label on the **right**
  (top/bottom edges may use up/down). Labels are pushed toward the **map edges**.
- Lines are **orthogonal polylines** (right-angle / "Manhattan" routing) with
  **90° bends**, NOT straight diagonals. When a direct route would cross a badge,
  the polyline **diverts** (adds a bend) to route around it.
- Implement as multi-segment polylines; validate every segment against all badge
  circles (reuse/extend `_seg_hits_badge`), reroute on collision.

### R3 — Avoid clutter
- Labels must not overlap each other or badges. If a label cannot be placed
  cleanly, **drop it** rather than overlap.
- Prefer fewer, edge-anchored labels over a dense web of crossing lines.
- Leave breathing room: the centre of the map stays readable; labels migrate
  outward.

### R4 — Small maps show ALL labels
- When the map has **fewer than 70 badges**, **every** label MUST be displayed —
  no label may be dropped for clutter (R3's drop rule is suspended below 70).
- The placement search must therefore be exhaustive enough (more candidate slots,
  wider radii, both sides, longer detours) to find a clean spot for every label
  at low counts. Dropping is only permitted at **≥ 70 badges**.
- R2 still holds at all counts: even when forcing all labels, no leader line may
  cross a badge. If geometry is truly impossible, expand the canvas search area /
  push labels further to the edges rather than cross a badge.

---

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

## Base map source (R1) — CARTO tiles, matching Leaflet
The live map (`map.js:10`) uses CARTO raster tiles; the export MUST use the same
so the output matches what the user sees:
| `style` param | Tile URL (single source of truth) |
|---------------|-----------------------------------|
| `dark` | `https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png` |
| `light` | `https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png` |

`_TILE_SERVERS` in `views.py:861` already holds these — R1's job is to make sure
they are actually rendered, not bypassed.

### R1 status & the OOM tension (must solve, don't bypass)
- `_make_background(use_tiles=True)` stitches all covering tiles into ONE big RGBA
  canvas then crops → at z≈7 full-Europe that canvas is ~98 MB → **OOM on the
  512 MB dyno**. The current "fix" sets `use_tiles=False` everywhere, which falls
  back to the gross Natural-Earth polygons → **R1 violation**.
- **Correct fix — memory-bounded tiling:** never build the giant stitch canvas.
  1. Pick the zoom where the bbox fits the output (existing logic).
  2. Allocate only the **W×H output image** (HD = ~3.7 MB).
  3. For each covering tile, fetch 256×256, compute its destination offset in the
     output image, and `paste` it directly (one tile in memory at a time).
  4. Peak memory = output image + one tile ≈ a few MB. No crop-of-giant-canvas.
- Cache tiles to `/tmp` like badges so repeat exports are fast.

## Dot colour schemes
**`surface`** (default):
- `#f5c542` — Artificial
- `#4caf50` — Grass / Natural
- `#2196f3` — Hybrid
- `#888888` — Unknown

**`country`**: auto-assign from a fixed palette of 12 distinct colours cycling per unique country name.

**`single`**: use `dot_color` param hex value for all dots.

## Overlay rendering (Pillow, drawn in order)
1. Base map (CARTO tiles, see R1) — memory-bounded tiling
2. Badges/dots: white ring + club badge (or coloured dot fallback)
3. Labels (if `labels=1`) — see **Label placement algorithm (R2/R3)** below
4. Legend box (if `legend=1`): semi-transparent dark pill, bottom-left
5. North arrow (if `north=1`): filled triangle + "N", top-right
6. Title bar (if `title`): bold text on dark rounded-rect, top-centre (+ subtitle)
7. Logo (if `logo=1`): "stadiumsofeurope.com", bottom-right

## Label placement algorithm (R2/R3)
Target behaviour (the Transfermarkt-style reference the user shared):
1. **Side assignment:** badge in left half → label anchored on the left, pushed
   toward the left edge; right half → right edge. (Top/bottom rows may go up/down.)
2. **Candidate slots:** generate edge-ward candidate positions ordered outermost-
   first so labels migrate to the map perimeter (reduces central clutter, R3).
3. **Collision test per candidate:**
   - label box vs all placed label boxes → reject on overlap (R3)
   - label box vs all badge circles → reject on overlap (R3)
   - **leader polyline vs all badge circles → reject if any segment hits a badge
     (R2);** if the straight route hits, try an orthogonal detour (extra 90° bend)
     before rejecting.
4. **Leader line = orthogonal polyline** (horizontal then vertical, or vice-versa)
   with 90° bends — never a diagonal straight line. Anchor at the badge-ring edge
   on the label's side; terminate at the label pill's near edge.
5. If no candidate passes after all slots + detours → **drop the label** (R3),
   don't force an overlapping/crossing one. **Exception (R4):** when total badge
   count < 70, dropping is forbidden — widen the search (more slots, larger radii,
   both sides) until every label is placed without crossing a badge.

## Files that will change
| File | Change type | Why |
|------|-------------|-----|
| `italianstadia/settings.py` | Edit | Add `MAPTILER_API_KEY` env read |
| `italiastadiaapp/views.py` | Edit | Add `map_export` view + helper functions |
| `italiastadiaapp/urls.py` | Edit | Register `/api/export/map/` |
| `requirements.txt` | Edit | Pin Pillow explicitly |
| `italiastadiaapp/tests/test_api.py` | Edit | Smoke tests |

## Implementation steps (✓ = done; open items are the R1/R2/R3 work)
Core export, Stripe gating, sizes, styles, filters, title/logo, label
size/colour, aspect-correct projection — **already shipped**. Remaining work is
bringing the render up to the three rules above:

1. [ ] **R1:** rewrite `_make_background` tiling to be memory-bounded — paste each
       CARTO tile directly into the W×H output (no giant stitch+crop), `/tmp`
       tile cache, then re-enable `use_tiles=True` for normal exports.
2. [ ] **R1:** verify dark export visually matches the Leaflet `dark_all` map.
3. [ ] **R2:** add orthogonal (90°-bend) leader-line routing in
       `_draw_dots_and_labels`; replace the straight `draw.line` with a polyline.
4. [ ] **R2:** enforce the left/right side rule by map-half before the radial slot
       search; validate every polyline segment against badge circles, detour on hit.
5. [ ] **R3:** drop labels that can't be placed without overlap/crossing; bias
       candidates outward to keep the centre clear.
6. [ ] **R4:** when badge count < 70, never drop — widen the candidate search
       (more slots/radii/sides) until all labels are placed.
7. [ ] Smoke test each rule (see Test plan).

## Test plan
- `test_map_export_returns_png` — GET with no params → 200, content-type image/png
- `test_map_export_surface_filter` — `?surface=ARTIFICIAL` → 200, PNG
- `test_map_export_no_results` — filter with no matches → 400 with JSON error
- **R1 manual:** export dark England map, overlay next to the Leaflet map — tiles
  must look the same (not blocky polygons). Confirm dyno stays < 512 MB.
- **R2 manual:** export with labels on → inspect: no leader line touches any badge;
  left badges → left labels, right badges → right labels; all bends are 90°.
- **R3 manual:** dense filter (e.g. all England) → no overlapping labels; unplaceable
  labels are dropped, centre stays readable.
- **R4 manual:** filter to < 70 badges (e.g. one league) → EVERY label is shown,
  none dropped, and R2 still holds (no line crosses a badge).

## Rollback plan
- Remove `map_export` from `views.py` and its URL from `urls.py`
- No migration needed
