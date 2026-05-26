# Feature Plan — Country filter on list pages
_Created: 2026-05-26 | Branch: feature/list-country-filter_

## Problem / Goal

After adding Bundesliga data, the three list pages (`/stadiums/`, `/teams/`, `/cities/`) now
show mixed Italian + German data under Italy-specific headings ("Italian Teams", "Serie A", etc.)
and have no way to narrow to a single country.

The fix must:
- Add a **country filter** (`?country=Germany`) to all three pages, defaulting to "All countries"
- Replace the **Italy-hardcoded tier sections** (`serie-a / serie-b / serie-c`) on stadiums and
  teams pages with **dynamic league sections** derived from the actual League objects in the DB
- Update the page-top anchor nav to match the new dynamic sections
- Make the hardcoded "Italian …" headings and descriptions responsive to the selected country

Success: selecting a country shows only stadiums/teams/cities from that country, grouped by their
leagues; "All countries" shows everything correctly.

## Scope

**In scope:**
- [ ] `stadium_list` view: replace hardcoded tier buckets with league-based sections; add `?country` filter
- [ ] `team_list` view: same — league-based sections + `?country` filter
- [ ] `city_list` view: add `?country` filter (keeps flat list, no sections needed)
- [ ] All three templates: add `<select>` country dropdown in the fixed nav; update section headings;
  remove hardcoded "Italian …" strings
- [ ] Tests: country filter returns correct subset; "All countries" returns all data

**Out of scope (do not touch):**
- Map page (`index.html` / `map.js`) — has its own country filter, untouched
- Stadium detail page
- GeoJSON API endpoints
- Models / migrations (no schema changes needed)
- Pagination (not in scope for this iteration)

## Design decisions

1. **Server-side filter (`?country=X`) vs client-side JS hide/show**
   — Chosen: server-side GET param. Reason: simpler, no extra JS, works without JS, consistent with
   Django conventions. Trade-off: page reloads on filter change (acceptable for list pages).

2. **League sections vs tier sections**
   — Chosen: group by `League` object ordered by `(league.country.name, league.division_level)`.
   This generalises naturally: Italy keeps Serie A → B → C; Germany gets Bundesliga;
   future leagues auto-appear without code changes.
   — Rejected: keep tiers 1/2/3 with country-aware labels. Reason: `tier` is an Italy-specific
   field (`tier=1` = Serie A); other countries don't use that numbering meaningfully.

3. **Stadium → league assignment**
   — A stadium's section is determined by its **primary league**: the team with the lowest
   `division_level` that plays there. Stadiums with no teams with a league FK go into a
   fallback "Other" section so no stadium disappears.

4. **City country source**
   — `City.country` is a plain `CharField`. Available choices come from
   `City.objects.values_list('country', flat=True).distinct().order_by('country')`.
   No model change needed.

5. **Anchor IDs for nav links**
   — Use `league-{{ league.id }}` as the HTML `id` anchor. The fixed nav renders one button
   per section. Fallback section uses `id="other"`.

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/views.py` | Edit | Rewrite `stadium_list`, `team_list`, `city_list` |
| `italiastadiaapp/templates/stadium_list.html` | Edit | Dynamic sections, country `<select>`, updated headings |
| `italiastadiaapp/templates/team_list.html` | Edit | Dynamic sections, country `<select>`, updated headings |
| `italiastadiaapp/templates/city_list.html` | Edit | Country `<select>`, remove hardcoded "Italian Cities" |
| `italiastadiaapp/tests/test_views.py` | Edit | Add country filter tests |

## New view contracts

### `stadium_list`
```python
request.GET.get("country", "")  # "" = all countries

# context
{
    "sections": [
        {
            "league": <League obj>,          # None for fallback section
            "league_label": "Bundesliga",    # display name
            "anchor": "league-3",            # HTML id
            "stadia": [<Stadium>, ...],      # ordered by capacity desc
        },
        ...
    ],
    "countries": ["Germany", "Italy", ...],  # sorted, all countries in DB
    "selected_country": "Germany",           # or ""
}
```
Sections ordered by `(league.country.name, league.division_level)`.

### `team_list`
```python
# context
{
    "sections": [
        {
            "league": <League obj>,
            "league_label": "Serie A",
            "anchor": "league-1",
            "teams": [<Team>, ...],          # ordered by average_attendance desc
        },
        ...
    ],
    "countries": [...],
    "selected_country": "",
}
```

### `city_list`
```python
# context
{
    "cities": [<City>, ...],            # filtered, ordered by -population, name
    "countries": [...],
    "selected_country": "",
}
```

## Implementation steps

1. [ ] Rewrite `stadium_list` view — build league sections, apply `?country` filter,
       pass `countries` list and `selected_country`
2. [ ] Rewrite `team_list` view — same pattern
3. [ ] Update `city_list` view — add `?country` GET filter and `countries` context
4. [ ] Update `stadium_list.html` — country `<select>` in fixed nav; `{% for section %}`
       keyed by `section.league`; remove hardcoded "Italian Stadiums"
5. [ ] Update `team_list.html` — same template changes
6. [ ] Update `city_list.html` — country `<select>`, remove "Italian Cities"
7. [ ] Add tests to `test_views.py`

## PostgreSQL safety check

No model changes. ✓ Not applicable.

## Test plan

Add to `italiastadiaapp/tests/test_views.py`:
- `GET /stadiums/?country=Germany` → sections contain only German league(s)
- `GET /stadiums/?country=Italy` → sections contain only Italian leagues
- `GET /stadiums/` → all sections present
- `GET /stadiums/?country=Zzz` → 200 OK, empty sections (not 404)
- `GET /teams/?country=Germany` → only Bundesliga teams
- `GET /teams/` → all teams present
- `GET /cities/?country=Germany` → only German cities
- `GET /cities/` → all cities present

## Rollback plan

No migrations involved. Revert via `git revert` on the commits touching these 5 files.
