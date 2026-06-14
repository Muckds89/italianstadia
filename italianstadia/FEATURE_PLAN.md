# Feature Plan — Rich Auto-Generated Meta Descriptions
_Created: 2026-06-14 | Branch: main_

## Problem / Goal
Stadium pages fall back to a generic "Explore capacity, ownership…" description when
`stadium.description` is empty (most stadiums). Team pages use a flat
"Name — First Division" string that tells Google nothing useful. Tournament pages have
no `<meta name="description">` at all. Google shows these dull snippets in search
results, hurting click-through rate. Success = every page has a unique, fact-rich
description (~155 chars) generated from structured fields even when the text
description is blank.

## Scope
**In scope:**
- [ ] `stadium_detail` view: build `page_description` from capacity, city, year, teams, type
- [ ] `team_detail` view: build `page_description` from league, city, stadium, founded, titles
- [ ] `tournament_detail` view: build `page_description` from confirmed count, host countries, total matches
- [ ] Update `{% block meta %}` in `stadium_detail.html` and `team_detail.html` to use `page_description`
- [ ] Add `<meta name="description">` to `tournament_detail.html` (currently missing entirely)

**Out of scope (do not touch):**
- `city_list.html` — filtered list page, not a detail page
- `stadium_list.html` / `team_list.html` — list pages, generic description is fine
- Any model or migration change
- Map page (`index.html`)

## Design decisions
1. Generate description in the **view** (Python), not in the template | Alternative: template logic with `{% if %}` chains | Reason: Python is testable, readable, and doesn't clutter templates with long conditional blocks
2. Build description from structured fields, append `stadium.description` excerpt only if it adds non-redundant info | Alternative: use description field always | Reason: most stadiums have no description; those that do often repeat facts already in the generated sentence
3. Cap at 155 chars in the view (not via `|truncatechars` in template) | Alternative: truncate in template | Reason: avoids mid-word cuts; view can trim at word boundary

## Example outputs
- Stadium: `"Wembley Stadium — 90,000 capacity, London, England. Built 1923. Closed roof, grass surface. Home of England national team."`
- Team: `"Inter Milan — Serie A, Milan, Italy. Home ground: Stadio Giuseppe Meazza (75,923 capacity). Founded 1908. 19 league titles."`
- Tournament: `"UEFA Euro 2028 — 9 confirmed venues across England and Ireland. 51 matches. Wembley Stadium, Tottenham Hotspur Stadium, Emirates Stadium…"`

## Files that will change
| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/views.py` | Edit | Add `page_description` to context in stadium_detail, team_detail, tournament_detail |
| `italiastadiaapp/templates/stadium_detail.html` | Edit | Replace `desc` with `page_description` in `{% block meta %}` |
| `italiastadiaapp/templates/team_detail.html` | Edit | Replace generated string with `page_description` |
| `italiastadiaapp/templates/tournament_detail.html` | Edit | Add `<meta name="description">` block |

## Implementation steps
1. [ ] Add `_stadium_description()` helper in `views.py`
2. [ ] Add `_team_description()` helper in `views.py`
3. [ ] Add `page_description` to `stadium_detail` context
4. [ ] Add `page_description` to `team_detail` context
5. [ ] Add `page_description` to `tournament_detail` context
6. [ ] Update `stadium_detail.html` `{% block meta %}`
7. [ ] Update `team_detail.html` `{% block meta %}`
8. [ ] Add `<meta name="description">` to `tournament_detail.html`
9. [ ] Run tests

## Test plan
- `pytest italiastadiaapp/tests/ -q` — all 44 tests still pass
- Manual: visit `/stadiums/wembley-stadium/`, view source → description contains "90,000" and "London"
- Manual: visit `/teams/<id>/`, view source → description contains league name and stadium
- Manual: visit `/tournaments/uefa-euro-2028/`, view source → description tag present

## Rollback plan
- Pure Python/template change — revert commit, no migration needed
