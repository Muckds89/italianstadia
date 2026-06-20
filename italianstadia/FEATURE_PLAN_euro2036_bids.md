# Feature Plan — UEFA Euro 2036 (competing multi-country bids)

_Created: 2026-06-19 | Branch: main_

## Problem / Goal

Euro 2032 has a single host pairing (Italy + Turkey) and our tournament model treats a
tournament as one flat set of venues grouped by country. **Euro 2036 is different: the host
is not chosen yet — there are several competing BIDS, most of them joint multi-country
bids.** We need to show, per tournament, the rival bids and the venues each proposes, so a
user can compare "who is bidding with which stadiums."

Bids to model (all speculative / unofficial as of 2026 — label clearly as proposed):

| Bid | Countries | Notes |
|-----|-----------|-------|
| Poland (solo) | Poland | No official UEFA bid submitted |
| Nordic (joint) | Denmark, Sweden, Norway, Finland (Iceland sometimes) | Most-discussed rumour |
| Balkan (joint) | Croatia, Serbia, Bosnia & Herzegovina, North Macedonia | Fan/media discussion |

Success: `/tournaments/uefa-euro-2036/` renders the three bids as distinct groups, each
listing its countries and proposed venues on the map + list, clearly marked "proposed bid /
not awarded."

## Scope

**In scope:**
- [ ] Add a `bid` key to the existing `tournaments` JSONField entries (no schema change).
- [ ] `_tournament_venues` surfaces `bid` per venue; `tournament_detail` groups by bid when a
      tournament has bids (generic, not hardcoded to 2036).
- [ ] `tournament_detail.html` renders bid groups (bid → countries → venues) + a "proposed
      bids, host not yet chosen" intro; JSON-LD stays one `SportsEvent`.
- [ ] Data migration: tag bid venues with `{tournament:"UEFA Euro 2036", year:2036,
      status:"CANDIDATE", bid:"<name>"}`; create the missing venues.
- [ ] Extend `COUNTRY_FLAGS` for any bid country missing a flag.
- [ ] Export: a bid-coloured option for Euro 2036 (`color_by="bid"`) — points coloured by bid.

**Out of scope (do not touch):**
- The Euro 2028 / Euro 2032 tournament pages (must render exactly as today — the bid layer is
  additive and only activates when venues carry a `bid`).
- Any DB schema migration (the `bid` is a JSON key, like `status`/`matches`).
- Awarding logic / voting / dates — these are rumoured bids only.

## Design decisions

1. **Model bids as a `bid` string key inside the existing `tournaments` JSONField entry.**
   Alternative: a new `Bid`/`TournamentBid` model. Rejected — bids are just a grouping label
   over venues; the JSON pattern already powers Euro 2032 and needs zero migration. Entry:
   `{"tournament":"UEFA Euro 2036","year":2036,"status":"CANDIDATE","bid":"Nordic"}`.
2. **All Euro 2036 venues = status `CANDIDATE`.** Alternative: a new `PROPOSED`/`BID` status.
   Rejected — `CANDIDATE` already means "not confirmed"; the `bid` field carries the new
   meaning. Keeps the status palette/legend unchanged.
3. **Grouping is bid-first, country-second, and auto-detected.** If any venue of a tournament
   has a `bid`, the detail page switches to bid groups (each bid box lists its countries +
   venues); otherwise it renders today's country grouping. So Euro 2032 is untouched and any
   future multi-bid tournament works for free.
4. **Joint bids are inherently multi-country** — the existing country sub-grouping nests inside
   each bid box (Nordic → Denmark / Sweden / Norway / Finland venues).
5. **Reuse national stadiums already added** (PGE Narodowy, Parken, Strawberry Arena=Friends,
   Bolt Arena, Rajko Mitić, etc.) as bid venues rather than duplicating.

## Data audit — bid venues (existing vs to create)

**Already in DB (reuse):** PGE Narodowy, Enea Poznań, Polsat Plus Arena Gdańsk (Poland) ·
Parken (Denmark) · Strawberry Arena = Friends Arena (Sweden) · Bolt Arena (Finland) ·
Maksimir, Poljud (Croatia) · Rajko Mitić (Serbia) + New National Stadium (Serbia, dev) ·
Koševo City Stadium (Bosnia) · Nacionalna Arena Tose Proeski (North Macedonia).

**Missing — create with coords (Wikipedia/Wikidata, OSM fallback):**
- Poland: Stadion Śląski (Chorzów), Tarczyński Arena (Wrocław), a Kraków venue (Cracovia or
  Wisła's Reymonta).
- Nordic: Ullevaal Stadion (Oslo, Norway), Laugardalsvöllur (Reykjavík, Iceland).
- Balkan: Bilino Polje (Zenica, Bosnia) — optional second Bosnian venue.
- (Denmark/Sweden/Finland national grounds already exist via the national-teams work.)

Apply the same scrape-QA name/coord rules from CLAUDE.md when creating these.

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `italiastadiaapp/migrations/00XX_euro2036_bids.py` | New | Create missing venues + tag all bid venues' `tournaments` JSON with the 2036 bid entry |
| `italiastadiaapp/views.py` | Edit | `_tournament_venues` adds `bid`; `tournament_detail` builds bid groups + intro; `COUNTRY_FLAGS` extend; export `color_by="bid"` + `_BID_COLOR`/legend |
| `italiastadiaapp/templates/tournament_detail.html` | Edit | Render bid-group boxes when present; keep country grouping otherwise |
| `italiastadiaapp/tests/test_views.py` | Edit | Tests: 2036 groups by bid; 2032 still groups by country |

## Implementation steps (bottom-up)

1. [ ] Data migration: create missing venues (slug + coords + city), then tag every bid
       venue's `tournaments` JSON with `{tournament, year:2036, status:CANDIDATE, bid}`.
2. [ ] `views.py`: `_tournament_venues` → include `bid` in each venue dict.
3. [ ] `views.py`: `tournament_detail` → if any venue has a `bid`, build `bids_by_name`
       (bid → {countries → venues}); pass `has_bids`, `bids`, and a bid-aware intro.
4. [ ] `tournament_detail.html`: render bid boxes (bid title + country sub-groups + venue
       cards + mini-map markers); fall back to existing country grouping when `not has_bids`.
5. [ ] `views.py`: extend `COUNTRY_FLAGS` for any missing bid country.
6. [ ] Export (optional this iter): `color_by="bid"` with `_BID_COLOR` palette + legend, and
       a bid filter so a Euro 2036 export can show rival bids in distinct colours.
7. [ ] Tests + regenerate static GeoJSON (operational venues unchanged; tournaments JSON now
       carries 2036 entries — `generate_stadiums_json` if any operational stadium gains it).

## PostgreSQL safety check
- [x] No new model field — `bid` is a key in the existing `JSONField` (like `status`/`matches`). No migration-schema risk; the data migration only writes JSON + creates rows (same pattern as 0048/0051/0060).
- [ ] New stadium rows: `name` CharField(255) ✓, coords `DecimalField` ✓, optional fields `null=True` ✓ (reuse the existing Stadium model — no new fields).

## Test plan
- `pytest italiastadiaapp/tests/test_views.py -k tournament` — add:
  - `test_euro2036_groups_by_bid`: GET `/tournaments/uefa-euro-2036/` → context has 3 bids
    (Poland/Nordic/Balkan), each with its countries; response contains "Nordic".
  - `test_euro2032_still_groups_by_country`: GET `/tournaments/uefa-euro-2032/` → no bid
    groups, country grouping intact (regression guard).
- Manual: open the 2036 page — three bid boxes, each with flags + venues; mini-map shows all;
  intro says "proposed bids — host not yet selected." Export with `color_by=bid` shows three
  colours + legend.

## Rollback plan
- Data only: `python manage.py migrate italiastadiaapp 0060_more_national_teams` (the 2036
  migration's `backwards` removes the 2036 tournaments-JSON entries and the venues it created).
- View/template are additive and bid-gated; reverting the migration makes the 2036 page 404
  again with zero effect on Euro 2028/2032.
```
