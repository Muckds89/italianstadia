# Feature Plan — Competitor Gap: Quick Wins + Medium Effort
_Created: 2026-06-13 | Branch: feature/stadium-metadata-and-slug_

## Problem / Goal

Comparison with worldstadiumsmap.com revealed several gaps. This plan closes
all quick wins and medium effort items deferred from that analysis:

- **Slug URLs** — `/stadium/123/` leaks internal IDs; `/stadium/san-siro/` is
  SEO-friendly and shareable. External links survive DB resets.
- **Stadium type & surface** — "Open stadium", "Grass" are common reference
  data competitors show; we store neither.
- **Year opened in popup** — `year_of_construction` exists in the model but
  isn't in the GeoJSON or popup, so users have to click through to see it.
- **Architect field on Stadium** — already on `StadiumDevelopment`; the main
  `Stadium` model has no equivalent despite Wikipedia having it.
- **Tournament history** — which major events were hosted is a high-value fact
  (World Cup groups, Euro finals) that competitors surface; we have nowhere to
  store it.
- **Country stats page** — `/country/Italy/` style pages with aggregated totals
  (stadiums, seats, avg capacity, leagues) improve SEO and discoverability.

Success = every stadium has richer metadata visible in the popup and detail
page; slug URLs are live with redirects from old numeric URLs; a country stats
page exists for every country with data.

---

## Scope

**In scope:**
- [ ] Add `slug`, `stadium_type`, `surface`, `architect`, `tournaments`
      fields to `Stadium` (one migration, 0041)
- [ ] Migration RunPython: auto-generate slugs from name, deduplicate
- [ ] Expose `slug`, `year_of_construction`, `stadium_type`, `surface`,
      `architect` in GeoJSON (`_build_stadium_features` + static JSON regen)
- [ ] Add year, type, surface to `buildPopupContent` in map.js; update
      popup link `/stadium/${props.id}/` → `/stadium/${props.slug}/`
- [ ] New URL `stadium/<slug:slug>/` + redirect view for old `stadium/<int:id>/`
- [ ] Update `stadium_detail` view to look up by slug
- [ ] Update ALL template links that point to stadium_detail
- [ ] Country stats view + URL + template
- [ ] Link country headers in `stadium_list.html` to country stats page
- [ ] Admin: expose new fields on StadiumAdmin
- [ ] Tests: GeoJSON includes new fields; slug URL resolves; redirect works;
      country stats page loads

**Out of scope:**
- Scraping `stadium_type`, `surface`, `architect` (data entry via admin only for now)
- `tournaments` data entry (field added, filled manually via admin)
- Global scope (non-European leagues)
- Stadium list filter by type or surface (separate feature)

---

## Design decisions

1. **Slug on Stadium only** | Alternative: slug on City/League too |
   Reason: Stadium detail is the only page with a numeric-ID URL that needs
   fixing now. City and League pages don't have detail URLs yet.

2. **Slug generation: `slugify(name)`, deduplicate with suffix `-2`, `-3`** |
   Alternative: `slugify(name + "-" + city)` | Reason: shorter URLs; city
   suffix only added on collision (rare — most stadium names are unique).

3. **Keep `stadium/<int:id>/` as permanent redirect (301)** | Alternative:
   remove old URL | Reason: external links, Transfermarkt backlinks, and any
   bookmarks all reference numeric IDs. Redirect costs nothing.

4. **`stadium_type` and `surface` as CharField with choices, null=True** |
   Alternative: separate lookup tables | Reason: the set of valid values is
   small and stable; CharField choices avoids an extra join and model.

5. **`tournaments` as JSONField `[{tournament, year, status, matches}]`** |
   Alternative: M2M to a Tournament model | Reason: data is sparse; JSONField
   lets admin fill it freely. Status values: `"CONFIRMED"` or `"CANDIDATE"`.
   Primary use-case: UEFA Euro 2028 and 2032 hosting bids/confirmations.

6. **Country stats at `/country/<country_name>/`** | Alternative:
   `/stats/country/<country_name>/` | Reason: mirrors worldstadiumsmap.com
   `/country/se` pattern; shorter, more discoverable.

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/models.py` | Edit | Add slug, stadium_type, surface, architect, tournaments |
| `italiastadiaapp/migrations/0041_…py` | New | Migration + RunPython slug backfill |
| `italiastadiaapp/views.py` | Edit | slug lookup; new country_stats + redirect views |
| `italiastadiaapp/urls.py` | Edit | Slug URL, redirect URL, country stats URL |
| `italiastadiaapp/admin.py` | Edit | Expose new Stadium fields |
| `italiastadiaapp/static/js/map.js` | Edit | Popup year/type/surface; link uses slug |
| `italiastadiaapp/templates/stadium_detail.html` | Edit | Show architect, type, surface, tournaments |
| `italiastadiaapp/templates/stadium_list.html` | Edit | Country headers → /country/X/ links |
| `italiastadiaapp/templates/country_stats.html` | New | Country aggregated stats page |
| `italiastadiaapp/tests/test_api.py` | Edit | New GeoJSON fields; slug URL; redirect |
| `italiastadiaapp/tests/test_views.py` | Edit | Country stats page loads |

---

## Implementation steps

### Phase A — Model & migration
1. [ ] `models.py`: add to `Stadium`:
   ```python
   slug         = models.SlugField(max_length=255, unique=True, blank=True)
   stadium_type = models.CharField(max_length=30, null=True, blank=True,
                    choices=[("OPEN","Open"),("CLOSED","Closed"),
                             ("RETRACTABLE","Retractable roof"),("INDOOR","Indoor")])
   surface      = models.CharField(max_length=20, null=True, blank=True,
                    choices=[("GRASS","Grass"),("ARTIFICIAL","Artificial"),("HYBRID","Hybrid")])
   architect    = models.CharField(max_length=255, null=True, blank=True)
   tournaments  = models.JSONField(default=list, blank=True)
   ```

2. [ ] `python manage.py makemigrations --name add_stadium_metadata_and_slug`

3. [ ] Patch migration with RunPython slug backfill:
   ```python
   from django.utils.text import slugify
   def backfill_slugs(apps, schema_editor):
       Stadium = apps.get_model("italiastadiaapp", "Stadium")
       seen = {}
       for s in Stadium.objects.order_by("id"):
           base = slugify(s.name) or f"stadium-{s.id}"
           slug, n = base, 2
           while slug in seen:
               slug = f"{base}-{n}"; n += 1
           seen[slug] = True
           s.slug = slug
           s.save(update_fields=["slug"])
   ```

### Phase B — Admin
4. [ ] `admin.py`: add `slug`, `stadium_type`, `surface`, `architect`,
       `tournaments` to `StadiumAdmin`; set
       `prepopulated_fields = {"slug": ("name",)}`.

### Phase C — GeoJSON
5. [ ] `views.py` `_build_stadium_features`: add to properties:
   ```python
   "slug":                 s.slug or str(s.id),
   "year_of_construction": s.year_of_construction,
   "stadium_type":         s.get_stadium_type_display() if s.stadium_type else "",
   "surface":              s.get_surface_display() if s.surface else "",
   "architect":            s.architect or "",
   ```
   (The static JSON command re-uses `_build_stadium_features` so it picks
   up these additions automatically — verify, no separate edit needed.)

### Phase D — Popup (map.js)
6. [ ] `buildPopupContent` (line 517): add after `Capacity` line:
   ```javascript
   ${props.year_of_construction ? `<strong>Opened:</strong> ${props.year_of_construction}<br>` : ""}
   ${props.stadium_type         ? `<strong>Type:</strong> ${props.stadium_type}<br>` : ""}
   ${props.surface              ? `<strong>Surface:</strong> ${props.surface}<br>` : ""}
   ```
7. [ ] Change popup `href` (line 528):
   `"/stadium/${props.id}/"` → `"/stadium/${props.slug || props.id}/"`

### Phase E — URLs & views
8. [ ] `urls.py`: replace old numeric URL, add slug + redirect + country stats:
   ```python
   path("stadium/<slug:slug>/",  stadium_detail,          name="stadium_detail"),
   path("stadium/<int:id>/",     stadium_detail_redirect,  name="stadium_detail_by_id"),
   path("country/<str:country_name>/", country_stats,     name="country_stats"),
   ```

9. [ ] `views.py` — change `stadium_detail` lookup to `slug=slug`.

10. [ ] `views.py` — add `stadium_detail_redirect`:
    ```python
    def stadium_detail_redirect(request, id):
        s = get_object_or_404(Stadium, pk=id)
        return redirect("italiastadiaapp:stadium_detail", slug=s.slug, permanent=True)
    ```

11. [ ] `views.py` — add `country_stats` view: aggregate total stadiums,
        total seats (sum of capacity), avg capacity, max capacity, leagues
        present, top 10 by capacity for that country.

### Phase F — Templates
12. [ ] `stadium_detail.html`: add architect, type, surface row to the
        existing data table; add tournaments section below (hidden when empty).

13. [ ] `stadium_list.html`: wrap each country `<h2>` in
        `<a href="{% url 'italiastadiaapp:country_stats' section.league.country.name %}">`.

14. [ ] `country_stats.html` (new): country name + flag, 4 stat cards
        (stadiums, total seats, avg capacity, max capacity), mini Leaflet map
        of that country's stadiums (reuses stadium coordinates from GeoJSON),
        top-10 table by capacity, leagues list, back-to-map link.

15. [ ] Update any other template links (`team_detail.html`,
        `team_list.html`, `stadium_development_detail.html`) that use
        `{% url 'italiastadiaapp:stadium_detail' stadium.id %}` →
        `{% url 'italiastadiaapp:stadium_detail' stadium.slug %}`.

### Phase G — Tests
16. [ ] `test_api.py`:
        - GeoJSON features contain `slug`, `year_of_construction`,
          `stadium_type`, `surface`, `architect`
        - `GET /stadium/<slug>/` → 200
        - `GET /stadium/<int:id>/` → 301, Location header contains slug URL

17. [ ] `test_views.py`:
        - `GET /country/Italy/` → 200
        - Response context contains `total_stadiums`, `total_seats`

---

## PostgreSQL safety check

- [x] `slug` SlugField(max_length=255), unique=True — safe, implicit index
- [x] `stadium_type` CharField(max_length=30) — adequate for choice labels
- [x] `surface` CharField(max_length=20) — adequate
- [x] `architect` CharField(max_length=255) — adequate for scraped names
- [x] `tournaments` JSONField(default=list) — no size limit, no IntegrityError
- [x] All new fields null=True or have default — no IntegrityError on migrate
- [x] No SmallIntegerField introduced

---

## Test plan

- `pytest italiastadiaapp/tests/ -v` — full suite green (currently 39 tests)
- Manual: `/stadium/san-siro/` loads the stadium detail page
- Manual: old `/stadium/1/` → 301 redirect to `/stadium/san-siro/`
- Manual: map popup shows "Opened: 1926" for San Siro
- Manual: `/country/Italy/` shows aggregated stats with correct counts
- Manual: country header in stadium list is now a clickable link

---

## Rollback plan

- Migration: `python manage.py migrate italiastadiaapp 0040_alter_league_name_…`
  (removes slug + all metadata columns; safe — all nullable or have default)
- JS: `git revert` the popup commit — no DB changes
- URLs: restore old `path("stadium/<int:id>/", stadium_detail, ...)` pattern
