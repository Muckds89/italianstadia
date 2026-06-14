# Feature Plan — JSON-LD Structured Data + Cookie Consent Banner
_Created: 2026-06-14 | Branch: main_

## Problem / Goal
Google and AI crawlers cannot extract structured facts from the site because
there is no schema.org markup. This suppresses rich results (knowledge panels,
event cards) and reduces crawl priority. AdSense approval also requires a
visible, GDPR-compliant cookie consent mechanism before setting any non-essential
cookies. Both are needed to improve SEO visibility and unblock the AdSense review.

## Scope
**In scope:**
- [ ] `StadiumOrArena` JSON-LD on `stadium_detail.html`
- [ ] `SportsOrganization` JSON-LD on `team_detail.html`
- [ ] `SportsEvent` JSON-LD on `tournament_detail.html` (one block per confirmed venue)
- [ ] Cookie consent banner (accept / reject) rendered site-wide via `base.html`
- [ ] `consent.js` — stores choice in `localStorage`, conditionally loads AdSense script only after accept
- [ ] `/privacy/` stub page — required by AdSense policy

**Out of scope (do not touch):**
- Map page (`index.html`) — no structured data needed there
- City detail page — no useful schema.org type
- Any new Django model or migration
- Changing existing view logic

## Design decisions
1. JSON-LD in `<script type="application/ld+json">` inside each detail template's `{% block extra_head %}` | Alternative: microdata attributes on HTML elements | Reason: JSON-LD is Google's recommended approach, easier to maintain, no HTML restructuring
2. Cookie consent stored in `localStorage` (key: `cookie_consent`) | Alternative: Django session cookie | Reason: no server round-trip; banner resolved before any Django session cookie is set
3. Plain Bootstrap toast for consent banner — no third-party CMP library | Alternative: Cookiebot / OneTrust | Reason: zero cost, no external JS dependency, sufficient for AdSense review
4. AdSense `<script>` injected dynamically by `consent.js` only on accept | Alternative: hardcode in `<head>` | Reason: GDPR requires explicit consent before loading advertising scripts

## Files that will change
| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/templates/base.html` | Edit | Add consent banner HTML + load consent.js |
| `italiastadiaapp/static/js/consent.js` | Create | Consent logic + conditional AdSense injection |
| `italiastadiaapp/templates/stadium_detail.html` | Edit | Add `StadiumOrArena` JSON-LD block |
| `italiastadiaapp/templates/team_detail.html` | Edit | Add `SportsOrganization` JSON-LD block |
| `italiastadiaapp/templates/tournament_detail.html` | Edit | Add `SportsEvent` JSON-LD blocks |
| `italiastadiaapp/templates/privacy.html` | Create | Privacy policy stub page (AdSense requirement) |
| `italiastadiaapp/views.py` | Edit | Add `privacy` view |
| `italiastadiaapp/urls.py` | Edit | Add `/privacy/` URL |

## JSON-LD schemas

### StadiumOrArena (stadium_detail.html)
```json
{
  "@context": "https://schema.org",
  "@type": "StadiumOrArena",
  "name": "Stadio Giuseppe Meazza",
  "address": { "@type": "PostalAddress", "addressLocality": "Milan", "addressCountry": "IT" },
  "geo": { "@type": "GeoCoordinates", "latitude": 45.478, "longitude": 9.124 },
  "maximumAttendeeCapacity": 75923,
  "url": "https://www.stadiumsofeurope.com/stadiums/san-siro/",
  "image": "<image_url>",
  "sport": "Football"
}
```

### SportsOrganization (team_detail.html)
```json
{
  "@context": "https://schema.org",
  "@type": "SportsOrganization",
  "name": "Inter Milan",
  "sport": "Football",
  "url": "https://www.stadiumsofeurope.com/teams/42/",
  "location": { "@type": "StadiumOrArena", "name": "Stadio Giuseppe Meazza" },
  "foundingDate": "1908"
}
```

### SportsEvent (tournament_detail.html — one per confirmed venue)
```json
{
  "@context": "https://schema.org",
  "@type": "SportsEvent",
  "name": "UEFA Euro 2028",
  "startDate": "2028",
  "sport": "Football",
  "location": { "@type": "StadiumOrArena", "name": "Wembley Stadium", "address": "London" },
  "organizer": { "@type": "Organization", "name": "UEFA" }
}
```

## Cookie consent banner behaviour
- First visit: toast slides up from bottom-right corner
- "Accept all" → `localStorage.cookie_consent = "accepted"` → AdSense script injected
- "Reject non-essential" → `localStorage.cookie_consent = "rejected"` → no AdSense
- Subsequent visits: localStorage read on page load, banner skipped, AdSense conditionally loaded
- Banner includes link to `/privacy/`

## Implementation steps
1. [ ] Create `italiastadiaapp/static/js/consent.js`
2. [ ] Edit `base.html` — add consent banner HTML + `{% block extra_head %}` if missing
3. [ ] Edit `stadium_detail.html` — add `StadiumOrArena` JSON-LD
4. [ ] Edit `team_detail.html` — add `SportsOrganization` JSON-LD
5. [ ] Edit `tournament_detail.html` — add `SportsEvent` JSON-LD
6. [ ] Create `privacy.html` template
7. [ ] Add `privacy` view + URL
8. [ ] Run tests

## Test plan
- `pytest italiastadiaapp/tests/ -q` — all 44 existing tests still pass
- Manual: visit `/stadiums/san-siro/`, view source, confirm `application/ld+json` present
- Manual: fresh browser → consent banner visible
- Manual: Accept → refresh → no banner, AdSense loads
- Manual: Reject → refresh → no banner, no AdSense

## Rollback plan
- All changes are additive (no model/migration) — revert template/static commits
- No database changes to undo
