# Feature Plan — Gallery Hero + Sticky Back-to-Map Nav (Stadium Detail)
_Created: 2026-05-28 | Branch: feature/gallery-hero_

## Problem / Goal

The stadium detail page needs:
1. A **scroll-snap carousel hero** (480px, full-width, `object-fit: cover`) with prev/next arrow buttons, dot indicators, and the stadium name overlaid bottom-left.
2. The **"← Back to map" link moved into the sticky navbar** (not left as a floating button in the page body), using a `{% block extra_nav %}` template block.

All JS goes in `static/js/stadium-detail-gallery.js`; no inline `<script>` blocks.

---

## Scope

**In scope:**
- [ ] `base_detail.html` — slim shared base for detail pages: site navbar + `{% block extra_nav %}{% endblock %}` + `{% block content %}{% endblock %}`
- [ ] `stadium_detail.html` extends `base_detail.html`; fills `extra_nav` with "← Back to map"; fills `content` with gallery hero + card body
- [ ] Gallery hero: full-width 480px, scroll-snap CSS carousel, `object-fit: cover`
- [ ] Carousel controls: prev/next arrow buttons (overlaid), dot indicators (bottom-centre)
- [ ] Stadium name overlay: bottom-left of hero
- [ ] JS in `static/js/stadium-detail-gallery.js` — dot generation, arrow nav, scroll sync
- [ ] CSS in `styles.css` — gallery hero, carousel track/slides, arrows, dots, name overlay
- [ ] Remove the standalone "← Back to map" `<a>` from the page body

**Out of scope:**
- No other templates extended from `base_detail.html` (index, list pages untouched)
- No new model fields
- No additional image sources (carousel supports N slides; current data has 1 per stadium — arrows/dots hidden when only 1 slide)

---

## Design decisions

1. **New `base_detail.html`, not a full site-wide `base.html`** — only the detail page needs the `extra_nav` slot right now. Keeping scope minimal avoids touching index.html, list pages, and their tests. | Alternative: site-wide base.html | Reason: would require refactoring all 6 other templates — scope creep.

2. **CSS scroll-snap carousel, not Bootstrap Carousel** — `scroll-snap-type: x mandatory` on a `display:flex` track; each slide is `flex: 0 0 100%`. No Bootstrap JS dependency, native browser scroll physics. | Alternative: Bootstrap Carousel | Reason: Bootstrap carousel needs its JS bundle and has animation quirks; scroll-snap is zero-JS for the sliding itself.

3. **JS only drives arrows + dots** — `scrollTo({behavior:'smooth'})` from arrow clicks; `scroll` event updates active dot. The actual snapping is pure CSS. | Alternative: full JS-driven carousel | Reason: less code, degrades gracefully if JS is slow.

4. **Name overlay bottom-left** — `position:absolute; bottom:1.5rem; left:1.5rem` inside `.gallery-hero`. No gradient needed for just the name (gradient handled separately if desired). | Alternative: below the hero | Reason: spec explicitly says "overlaid bottom-left".

5. **"← Back to map" in `{% block extra_nav %}`** — becomes a button appended to the site navbar. Always visible as the user scrolls down. | Alternative: sticky bar below hero (previous plan) | Reason: spec explicitly says "moves into sticky navbar via extra_nav block".

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/templates/base_detail.html` | **New** | Base with site nav + `extra_nav` + `content` blocks |
| `italiastadiaapp/templates/stadium_detail.html` | Edit | Extends `base_detail.html`; gallery hero in `content`; back-to-map in `extra_nav` |
| `italiastadiaapp/static/js/stadium-detail-gallery.js` | **New** | Dots, arrow clicks, scroll sync |
| `italiastadiaapp/static/css/styles.css` | Edit | `.gallery-hero`, `.gallery-track`, `.gallery-slide`, `.gallery-arrow`, `.gallery-dots`, `.gallery-dot`, `.gallery-name-overlay` |

---

## Implementation steps

1. [ ] **Create `base_detail.html`**:
   ```html
   {% load static %}
   <!DOCTYPE html>
   <html>
   <head>
     <meta charset="utf-8">
     <meta name="viewport" content="width=device-width,initial-scale=1">
     <title>{% block title %}Italian Stadia{% endblock %}</title>
     <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
     <link rel="stylesheet" href="{% static 'css/styles.css' %}">
     {% block extra_head %}{% endblock %}
   </head>
   <body class="bg-light">
   <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
     <div class="container d-flex align-items-center gap-3">
       <a class="navbar-brand me-0" href="/">Italian Stadia</a>
       <div class="navbar-nav flex-row">
         <a class="nav-link" href="{% url 'italiastadiaapp:home' %}">Map</a>
         <a class="nav-link" href="{% url 'italiastadiaapp:stadium_list' %}">Stadiums</a>
         <a class="nav-link" href="{% url 'italiastadiaapp:team_list' %}">Teams</a>
         <a class="nav-link" href="{% url 'italiastadiaapp:city_list' %}">Cities</a>
       </div>
       {% block extra_nav %}{% endblock %}
     </div>
   </nav>
   {% block content %}{% endblock %}
   {% block extra_scripts %}{% endblock %}
   </body>
   </html>
   ```

2. [ ] **Rewrite `stadium_detail.html`** to extend `base_detail.html`:
   - `{% block title %}{{ stadium.name }}{% endblock %}`
   - `{% block extra_head %}` — MapLibre CSS + inline `#stadium-detail-map` style
   - `{% block extra_nav %}` — `<a href="{% url 'italiastadiaapp:home' %}" class="btn btn-sm btn-outline-light ms-auto">← Back to map</a>`
   - `{% block content %}` — gallery hero, then `<div class="container my-5">` with card
   - Remove the old `← Back to map` button from inside the container
   - `{% block extra_scripts %}` — MapLibre JS + `stadium-detail-map.js` + `stadium-detail-gallery.js`

3. [ ] **Gallery hero HTML** (inside `{% block content %}`):
   ```html
   <div class="gallery-hero" id="galleryHero">
     <div class="gallery-track" id="galleryTrack">
       {% if stadium.image_url %}
       <div class="gallery-slide">
         <img src="{{ stadium.image_url }}" alt="{{ stadium.name }}">
       </div>
       {% endif %}
     </div>
     <div class="gallery-name-overlay">{{ stadium.name }}</div>
     <button class="gallery-arrow gallery-arrow-prev" id="galleryPrev" aria-label="Previous">&#8249;</button>
     <button class="gallery-arrow gallery-arrow-next" id="galleryNext" aria-label="Next">&#8250;</button>
     <div class="gallery-dots" id="galleryDots"></div>
   </div>
   ```

4. [ ] **Add CSS to `styles.css`**:
   ```css
   .gallery-hero {
     position: relative;
     width: 100%;
     height: 480px;
     background: #111;
     overflow: hidden;
   }
   .gallery-track {
     display: flex;
     height: 100%;
     overflow-x: scroll;
     scroll-snap-type: x mandatory;
     scroll-behavior: smooth;
     scrollbar-width: none;
   }
   .gallery-track::-webkit-scrollbar { display: none; }
   .gallery-slide {
     flex: 0 0 100%;
     height: 100%;
     scroll-snap-align: start;
   }
   .gallery-slide img {
     width: 100%;
     height: 100%;
     object-fit: cover;
     display: block;
   }
   .gallery-name-overlay {
     position: absolute;
     bottom: 1.5rem;
     left: 1.5rem;
     color: #fff;
     font-size: 2rem;
     font-weight: 800;
     text-shadow: 0 2px 8px rgba(0,0,0,0.7);
     pointer-events: none;
   }
   .gallery-arrow {
     position: absolute;
     top: 50%;
     transform: translateY(-50%);
     background: rgba(0,0,0,0.45);
     color: #fff;
     border: none;
     border-radius: 50%;
     width: 44px;
     height: 44px;
     font-size: 1.6rem;
     line-height: 1;
     cursor: pointer;
     transition: background 0.2s;
   }
   .gallery-arrow:hover { background: rgba(0,0,0,0.75); }
   .gallery-arrow-prev { left: 1rem; }
   .gallery-arrow-next { right: 1rem; }
   .gallery-dots {
     position: absolute;
     bottom: 1rem;
     left: 50%;
     transform: translateX(-50%);
     display: flex;
     gap: 6px;
   }
   .gallery-dot {
     width: 8px;
     height: 8px;
     border-radius: 50%;
     background: rgba(255,255,255,0.5);
     border: none;
     cursor: pointer;
     padding: 0;
     transition: background 0.2s;
   }
   .gallery-dot.active { background: #fff; }
   @media (max-width: 768px) {
     .gallery-hero { height: 300px; }
     .gallery-name-overlay { font-size: 1.4rem; }
   }
   ```

5. [ ] **Create `stadium-detail-gallery.js`**:
   ```javascript
   document.addEventListener('DOMContentLoaded', function () {
     const track = document.getElementById('galleryTrack');
     const prevBtn = document.getElementById('galleryPrev');
     const nextBtn = document.getElementById('galleryNext');
     const dotsEl = document.getElementById('galleryDots');
     if (!track) return;

     const slides = track.querySelectorAll('.gallery-slide');
     let current = 0;

     // Build dots
     slides.forEach(function (_, i) {
       const dot = document.createElement('button');
       dot.className = 'gallery-dot' + (i === 0 ? ' active' : '');
       dot.setAttribute('aria-label', 'Slide ' + (i + 1));
       dot.addEventListener('click', function () { goTo(i); });
       dotsEl.appendChild(dot);
     });

     function goTo(i) {
       current = Math.max(0, Math.min(i, slides.length - 1));
       track.scrollTo({ left: current * track.clientWidth, behavior: 'smooth' });
       syncDots();
     }

     function syncDots() {
       dotsEl.querySelectorAll('.gallery-dot').forEach(function (d, i) {
         d.classList.toggle('active', i === current);
       });
     }

     prevBtn.addEventListener('click', function () { goTo(current - 1); });
     nextBtn.addEventListener('click', function () { goTo(current + 1); });

     track.addEventListener('scroll', function () {
       const i = Math.round(track.scrollLeft / track.clientWidth);
       if (i !== current) { current = i; syncDots(); }
     }, { passive: true });

     // Hide controls when only one slide
     if (slides.length <= 1) {
       prevBtn.style.display = 'none';
       nextBtn.style.display = 'none';
       dotsEl.style.display = 'none';
     }
   });
   ```

6. [ ] Run `pytest italiastadiaapp/tests/ -v` — 18 tests pass

---

## PostgreSQL safety check

N/A — no model changes.

---

## Test plan

- `pytest italiastadiaapp/tests/ -v` — all 18 pass
- Manual: stadium with image → 480px hero, name bottom-left, arrows/dots hidden (1 slide)
- Manual: "← Back to map" visible in the navbar (top right), not in page body
- Manual: scroll deep into the page → back-to-map always reachable in the sticky navbar
- Manual: mobile ≤768px → hero 300px, name smaller, navbar back button still visible

---

## Rollback plan

All files on `feature/gallery-hero`. `git revert` the commit or `git checkout main -- <files>`.
