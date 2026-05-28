# Feature Plan — Gallery Hero on Stadium Detail Page
_Created: 2026-05-28 | Branch: feature/stadium-gallery-hero_

## Problem / Goal

The stadium detail page shows the stadium photo as a small `card-img-top` (260px, constrained inside Bootstrap's card). This wastes the full-resolution Wikipedia images now being stored. The goal is a full-bleed hero section above the card — a large stadium photo with a gradient text overlay showing the stadium name and key facts, plus a team badge strip below. The page should feel like a sports reference page, not a data table.

---

## Scope

**In scope:**
- [ ] Replace `card-img-top` with a full-bleed `.stadium-hero` section above the card
- [ ] Gradient overlay on the hero with stadium name, city, capacity
- [ ] Team badge strip: circular team badges with name labels, centred below the hero
- [ ] Dark placeholder fallback when `image_url` is None
- [ ] CSS for hero and badge strip in `styles.css`
- [ ] Mobile responsive: hero 300px on ≤768px

**Out of scope (do not touch):**
- No model changes — uses existing `stadium.image_url` and `team.image_url`
- No view changes — all data already in template context
- No JS changes
- No carousel (only one photo per stadium)
- No other page templates

---

## Design decisions

1. **Hero outside the card** — before `<div class="container">` so it spans full viewport width. | Alternative: keep inside card | Reason: full-bleed is the modern sports/reference look.
2. **Gradient overlay for text legibility** — `linear-gradient(to top, rgba(0,0,0,0.75), transparent)` from the bottom lets stadium name and stats stay readable on any image. | Alternative: white card below image | Reason: overlay avoids a visual break; text feels part of the photo.
3. **Badge strip below hero, not overlaid** — clean flex row between hero and card. | Alternative: badges as circular overlays on hero bottom edge | Reason: simpler; avoids z-index issues.
4. **No carousel** — one stadium photo per stadium; a single-image carousel adds DOM weight with no user benefit.

---

## Layout mockup

```
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│         [stadium photo — 500px tall, full bleed]             │
│                                                              │
│  Parc des Princes                        [gradient overlay]  │
│  Paris  ·  47,929 seats                                      │
└──────────────────────────────────────────────────────────────┘
            [badge]  [badge]           ← badge strip
            Paris    PSG II

┌─── .container ────────────────────────────────────────────────┐
│  ← Back to map                                               │
│  ┌─── .card ─────────────────────────────────────────────┐   │
│  │  [info table]  │  [map]                               │   │
│  │  [teams section]                                      │   │
│  └───────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────┘
```

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/templates/stadium_detail.html` | Edit | Hero section + badge strip replace `card-img-top` |
| `italiastadiaapp/static/css/styles.css` | Edit | `.stadium-hero`, `.stadium-hero-overlay`, `.stadium-badge-strip` |

---

## Implementation steps

1. [ ] Add CSS to `styles.css`:
   - `.stadium-hero` — `position:relative; height:500px; background:#111; overflow:hidden`
   - `.stadium-hero img` — `width:100%; height:100%; object-fit:cover`
   - `.stadium-hero-overlay` — absolute, bottom-0, left-0, right-0, gradient, padding
   - `.stadium-hero-title` — large white text, font-weight 800
   - `.stadium-hero-meta` — muted white text, smaller
   - `.stadium-badge-strip` — flex, justify-content-center, gap, padding, white bg
   - `.stadium-badge-item` — flex column, align-center, gap, small text
   - `.stadium-badge-img` — 64px circle, object-fit contain, white bg, shadow
   - `.stadium-badge-placeholder` — 64px circle, grey, initials
   - Mobile: `@media (max-width: 768px)` hero 300px

2. [ ] Edit `stadium_detail.html`:
   - Add `{% load humanize %}` at top for `intcomma` filter
   - Remove `{% if stadium.image_url %}<img class="card-img-top">{% endif %}` from inside the card
   - Add hero section **before** `<div class="container my-5">`
   - Add badge strip between hero and the `<div class="container">`

3. [ ] Run `pytest italiastadiaapp/tests/ -v` — 18 tests pass

---

## PostgreSQL safety check

N/A — no model changes.

---

## Test plan

- `pytest italiastadiaapp/tests/ -v` — full suite stays green
- Manual: open a stadium with `image_url` → hero visible, full-bleed, name overlay legible
- Manual: open a stadium with multiple teams → badge strip shows all team badges with names
- Manual: open a stadium without `image_url` → dark placeholder with name still visible
- Manual: mobile viewport → hero at 300px, badge strip wraps cleanly

---

## Rollback plan

Template + CSS only. `git revert` the commit on `feature/stadium-gallery-hero`.
