# Growth plan — 333 visits/day within ~1 month

## Where we are (from Search Console)
- We **rank** for many queries (avg position 5–30) but get **~0 clicks** → the problem is
  CTR + a few positions short of the top, NOT lack of impressions.
- Huge untapped queries already near page 1:
  - `strømsgodset toppfotball` — **967 impressions**, pos 10.7, 0 clicks
  - `euro 2032 stadiums/venues/location` — page 1, our strongest theme
  - long tail of `<club> stadium`, `<stadium> capacity`, `where is <club>`, `<club> full name`
- These are EXACTLY what our 900+ stadium/team pages answer. We're leaving clicks on the table.

## The math to 333/day
333 clicks/day ≈ converting existing impressions. If we surface ~50 club/stadium pages that
each pull 100–1,000 impressions/day and lift CTR from ~0% to 5–8% while climbing 2–4 positions,
that alone clears 333. The tournament + insight pages add a spike layer (social/backlinks).

---

## Pillar 1 — Win the clicks we already rank for (CTR) — WEEK 1
The fastest lever. We rank ~5–10 but nobody clicks → titles/snippets aren't compelling.
1. **Title tags = the exact query + the answer.**
   - Stadium: `<Stadium> — Capacity, Location & Pitch | Stadiums of Europe`
   - Team: `<Team> — Stadium, Capacity & Full Name | Stadiums of Europe`
2. **Meta descriptions that answer at a glance** (capacity, city, surface, founded) — already
   data-driven; tighten to lead with the number people search for.
3. **Answer block at the top of every stadium/team page** (snippet bait): a one-line
   "X has a capacity of N, located in City, Country, opened YEAR, natural-grass pitch."
   Google lifts these into featured snippets / AI answers.
4. **FAQ JSON-LD** on stadium & team pages ("What is X's capacity?", "Where does X play?",
   "What is X's full name?") — wins People-Also-Ask real estate. We already have
   StadiumOrArena/SportsTeam JSON-LD; add FAQPage.

## Pillar 2 — Climb the near-page-1 high-impression pages — WEEK 1–2
1. Pull the GSC "position 8–20, high impressions" list weekly; for each, deepen the page
   (more text, internal links, image with alt text, correct H1).
2. Start with **Strømsgodset** (967 impr): rich team page + stadium page + cross-links.
3. Ensure every such page is **indexed** (URL Inspection → Request Indexing) — new leagues
   just went live, so submit the sitemap and request indexing of the top 50 pages.

## Pillar 3 — Double down on the traffic magnets: tournaments + insights — WEEK 2–3
The Euro 2032/2036 pages and the insight pages are the share-worthy, link-worthy assets.
1. **Insight pages get hero maps** (backend-rendered topic images — see Pillar 5 tasks) and
   long-form, opinionated text (the artificial-turf/Cambiaso angle, national-stadium debate,
   Serie A reduction debate). These are the pages that earn backlinks.
2. **Promote them** (this is what actually moves the needle in a month):
   - Reddit r/soccer, r/football, country subs — the artificial-turf map post (Cambiaso /
     Bodø-Glimt angle) is tailor-made; the national-stadium and density debates too.
   - X/Twitter football-data community; tag relevant accounts.
   - Each good post = referral traffic spike + backlinks → rankings rise site-wide.
3. Build a "Euro 2032 / 2036" internal hub linking every venue page (topical authority).

## Pillar 4 — Internal linking & topical authority — WEEK 2–4
- Cross-link Team ↔ Stadium ↔ City ↔ Tournament ↔ Insight everywhere ("Related").
- Country hub pages (`/country/<name>/`) listing all that country's stadiums/teams — strong
  for `<country> football stadiums` queries.
- Add Export + Tournaments + Insights to the detail-page navbar (done) so crawlers and users
  reach the magnet pages from every page.

## Pillar 5 — Concrete build tasks (this batch + next)
Done now:
- Detail-page navbar: add **Export** and **Tournaments**.
- Insight content: artificial-turf Cambiaso/Bodø narrative; national-stadium "who's debating
  one" paragraph (Croatia, Stadio Olimpico post Lazio/Roma); density = **top-tier only** map +
  Serie A 20→18/16 debate paragraph.

Next (the heavier engineering — backend topic maps, reuses the tournament-map stack
`_compose_export_image` / `_spotlight_country`):
- `generate_insight_maps` command producing a hero PNG per insight, regenerated on data change:
  - **National-team-only**: satellite base, spotlight the nations that HAVE such a ground,
    dim the rest, flag badges on each — refresh whenever a new national-only ground appears.
  - **Surface**: markers coloured grass/hybrid/artificial.
  - **Density (top tier)**: choropleth shaded by top-flight stadiums per million.
- Insight cards + page headers embed these heros (CTR + social preview images / og:image).
- Add the og:image per page = the topic map (better social unfurls → more clicks).

## Pillar 6 — Measure weekly
- GSC: track clicks, CTR, avg position for the top 50 queries weekly.
- Target trajectory: ~30–50/day (wk1 CTR fixes) → ~120 (wk2 indexing + climbs) →
  ~250 (wk3 social spikes + backlinks) → 333+ (wk4 compounding rankings).
- If a social post lands, expect a one-day spike of 500–2,000; convert that into lasting
  rankings via the on-page work above.

## 7-day query data — demand is capacity, Euro 2032, club facts (not the current insights)
Re-reading Search Console (last 7 days) changes the priority order:
1. **Stadium capacity is the dominant long-tail intent** — `fk auda stadium` (30 impr, pos 5.8),
   `marsaxlokk fc stadium` (21), `marsaxlokk stadium` (13), plus a stream of
   `<club> capacity` (goztepe, psv eindhoven, lotto park, aik, karlsruher, cremonese,
   wigan, ail arena, bryne…). All page-1, ~0 clicks → snippet not leading with the number.
2. **Euro 2032 is the only converter** — `euro 2032 stadiums` 6 clicks / 42 impr / pos 4.9;
   many page-1 variants. Climb to #1.
3. **FC Nantes factoid storm** — ~15 variants of "FC Nantes founded 1943 merger of five
   local clubs", pos ~4–6, zero clicks. Quiz/LLM-driven; we rank but don't surface the fact.
4. **"where is X" / "X from which country"** and **"<country> football stadiums"** (romanian).

Action reprioritisation (do these BEFORE more social-bait insights):
- **Capacity-led titles + answer block + FAQ on every stadium page** — biggest sitewide CTR
  win (converts the dozens of page-1 zero-click capacity queries).
- **NEW insight: "Biggest & smallest stadiums in Europe" (ranked, by league/country)** —
  matches the capacity intent at scale and is highly shareable.
- **Founding/history answer block + FAQ on team pages** (the Nantes pattern).
- **Euro 2032**: make the page the definitive guide; internal-link every venue.
- **Country hub pages** for "<country> football stadiums".
Note: the current three insights (national-only, surface, density) are SOCIAL link-bait, not
search-demand matches — keep them for promotion, but the search money is capacity + Euro 2032.

## Honest caveat
333/day in 30 days is achievable ONLY if (a) the CTR/snippet work ships in week 1 and (b) at
least one insight post gets traction on Reddit/X. SEO ranking gains take 2–6 weeks to register;
the social/backlink layer is what compresses it into a month. Without promotion, organic alone
likely reaches ~333 closer to 6–10 weeks.
