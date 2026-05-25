# Feature Plan — Scroll-triggered 3D map animation on stadium detail page
_Created: 2026-05-25 | Branch: feature/scroll-triggered-map-animation_

## Problem / Goal

The stadium detail page has a MapLibre 3D fly-in animation (zoom 12→16.5, pitch 35→65,
bearing -90→0 over 6.5 s) that fires the moment the map tile layer loads — even if the
user has not yet scrolled to see the map. On mobile the map card is below the fold, so
the animation completes unseen before the user reaches it. On desktop the card is
side-by-side with the stadium info, so it is visible, but the animation still fires during
page load rather than as a deliberate reveal.

Success: the animation fires only when the map container is ≥ 40% visible in the
viewport; a "Replay ↺" button lets the user re-trigger it; if the user scrolls the map
out of view the state resets so the animation replays on next entry.

## Scope

**In scope:**
- [ ] Replace `map.on("load")` animation trigger with an `IntersectionObserver`
- [ ] Handle the race condition: map may finish loading before or after the container scrolls into view — animation only starts when BOTH conditions are true
- [ ] Add a "Replay ↺" button below the map card that re-runs the animation
- [ ] Disconnect the observer after the animation fires (one-shot) — no auto-replay on re-entry
- [ ] Fix duplicate `maplibre-gl` CSS `<link>` in `stadium_detail.html` (loaded twice)
- [ ] Fix mismatch between map init state (`pitch: 60, bearing: -25`) and animation start values (`pitch: 35, bearing: -90`) — init state should match animation start so there is no visual jump

**Out of scope (do not touch):**
- The animation parameters themselves (zoom range, pitch range, bearing range, duration, easing) — these are already tuned
- `map.js` (main dashboard map) — completely separate file
- Any backend / model / migration change
- The orbit/loop behaviour mentioned in the roadmap (Phase 5 enhancement)

## Design decisions

1. **IntersectionObserver over scroll event listener** | Alternative: `window.addEventListener("scroll", ...)` | Reason: IntersectionObserver fires a callback only when threshold is crossed (no per-frame polling), cleaner teardown, and natively handles the "already visible on load" case.

2. **threshold: 0.4** | Alternative: 0.1 or 1.0 | Reason: 0.1 fires too early (map barely peeking), 1.0 requires full visibility which never happens on small mobile screens. 0.4 means roughly half the card is visible — a meaningful reveal moment.

3. **Track `mapLoaded` and `inView` as separate booleans, animate only when both true** | Alternative: nest the observer callback inside `map.on("load")` | Reason: nesting would miss the case where the map loads after scrolling in; two independent flags compose cleanly.

4. **Replay button in the template card-footer, not injected by JS** | Alternative: `document.createElement` in JS | Reason: the button is a UI element — it belongs in the template so it is visible in the HTML. JS only wires the click handler.

5. **One-shot observer (disconnect after first fire)** | Alternative: reset on scroll-out so animation replays on re-entry | Reason: user preference — animation plays once automatically, replay is always explicit via the button.

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/static/js/stadium-detail-map.js` | Edit | Replace load-triggered animation with IntersectionObserver logic |
| `italiastadiaapp/templates/stadium_detail.html` | Edit | Remove duplicate CSS link, fix map init values, add Replay button |

## Implementation steps

1. [ ] `stadium_detail.html` — remove the duplicate `maplibre-gl` CSS `<link>` (line 169, already loaded in `<head>` at line 9)
2. [ ] `stadium-detail-map.js` — change map init to `zoom: 12, pitch: 35, bearing: -90` to match animation start (eliminates the visual jump)
3. [ ] `stadium-detail-map.js` — introduce `let mapLoaded = false` and `let inView = false` flags; move animation into a `tryAnimate()` helper that runs only when both are true
4. [ ] `stadium-detail-map.js` — replace `map.on("load", ...)` trigger with `mapLoaded = true; tryAnimate()`
5. [ ] `stadium-detail-map.js` — add `IntersectionObserver` on `#stadium-detail-map` with `threshold: 0.4`; on enter set `inView = true`, call `tryAnimate()`, then disconnect the observer (one-shot)
6. [ ] `stadium_detail.html` — add Replay button in the map card-footer (alongside the existing Google Maps link)
7. [ ] `stadium-detail-map.js` — wire Replay button click: reset `animationPlayed` flag and re-run the animation
8. [ ] Manual test: open a stadium detail page on mobile viewport (375px), scroll down, confirm animation plays on map entry; scroll away and back, confirm it replays

## PostgreSQL safety check

N/A — no model changes in this feature.

## Test plan

- `pytest italiastadiaapp/tests/test_views.py::test_stadium_detail_page_loads` — existing test still passes (no template breakage)
- Manual on desktop: load detail page → map starts at correct init state → animation plays as map loads into viewport
- Manual on mobile (375px viewport): scroll to map card → animation plays → scroll away → scroll back → animation replays
- Manual: click "Replay ↺" → animation re-runs from start
- Manual: confirm no JS console errors on pages without a map container (guard `if (!mapContainer) return` is already present)

## Rollback plan

Pure JS/template change — no migration needed.
To revert: `git revert <commit>` or restore the two files from `main`.
No feature flag needed; the change is not behind a flag.
