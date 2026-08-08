# Self-hosted club crests

## Why

Crests are fetched from a third party **at render time**, on every export. That has
now failed twice in one week:

- **Transfermarkt** soft-blocked us — HTTP 200 with a zero-byte body — killing 999
  of 1,034 crests. Maps published with bare green dots before anyone noticed.
- **Wikimedia**, the replacement, throttles bursts. It dropped 17 of 18 badges on
  a cold cache until per-host concurrency was capped at 3.

The pattern is the same both times: *someone else's availability decides whether
our maps have badges*, and the failure is silent — a missing crest renders as a
plain dot, which looks like a design choice rather than an error.

Two aggravating factors:

- `_BADGE_DISK_CACHE` is `/tmp/soe_badges`. On Render's free tier that is wiped on
  every deploy, restart and spin-down, so the cache is almost always cold and each
  export re-pulls nearly every crest. Two months of re-fetching the same images is
  what tripped Transfermarkt's bot management.
- We are hotlinking. Serving another CDN's images to our visitors is what both
  hosts object to, and it will keep tripping thresholds as traffic grows.

## What

Download every crest once, commit it, serve it from our own domain. No network
call during a render.

This mirrors what the project already does for `stadiums_map.json`, the tournament
PNGs and the insight heroes: pre-generate, commit, serve statically — because the
free tier cannot be trusted to do work at request time.

## Scope

| | |
|---|---|
| Clubs with a crest | 1,014 |
| Clubs without | 36 (render as a plain dot; unchanged) |
| Formats | 688 svg, 326 png |
| Estimated size | 15–25 MB committed |

## Design

**Storage.** `italiastadiaapp/static/crests/<team-slug>.png` — one flat directory
keyed by the existing unique `Team.slug`, so no new uniqueness problem. Everything
is normalised to **PNG at 160 px**, the canonical fetch size already used by
`_prefetch_badges`:

- SVGs are rasterised once here rather than through the MediaWiki thumbnail API on
  every cold start, which removes `_svg_badge_png_url` from the render path
- one format means the renderer never branches on file type
- 160 px is large enough for the biggest badge the export draws and small enough
  that 1,014 files stay well under 25 MB

**New field.** `Team.crest_file` (`CharField(max_length=255, blank=True)`) holding
the filename only. Keeping `image_url` untouched preserves provenance and lets the
download command re-run; the renderer prefers `crest_file` and falls back to
`image_url` so nothing breaks mid-migration.

**New command.** `manage.py download_crests [--force] [--league X]`

1. for each club with `image_url` and no `crest_file` (or `--force`)
2. fetch, rasterise if SVG, fit through `_fit_badge_in_circle`, save PNG
3. write `crest_file`, report failures per club
4. respects the same per-host caps and the descriptive Wikimedia UA

**Renderer change.** `_prefetch_badges` reads from disk when `crest_file` is set.
The whole `ThreadPoolExecutor` + 22 s budget + retry + host-semaphore path stays,
but only ever runs for clubs still lacking a local file — in the steady state it
does nothing at all, so an export becomes pure CPU.

## Licensing

Unchanged in substance, but worth stating because the files move onto our domain:

- **Commons crests are freely licensed** and safe to redistribute; `image_credit`
  already records the source
- **Fair-use crests from Wikipedia** are club trademarks used to identify that club
  on a map — nominative use, the same basis on which they are used today
- self-hosting does not change what the images are used for, only who serves them

Attribution stays in `image_credit` and the existing "Data: Wikipedia &
Transfermarkt" footer needs revisiting once Transfermarkt is no longer a source
for crests.

## Steps

1. `Team.crest_file` + migration
2. `download_crests` command; run for all 1,014, review failures
3. `_prefetch_badges` prefers the local file
4. tests: local file wins over `image_url`; missing file falls back; no render
   makes a network call when every club has `crest_file`
5. commit crests + fixture; deploy
6. once green in production, drop the remote path to a warning

## Risks

- **Repo size.** 15–25 MB is a real increase. Acceptable — the repo already ships
  ~1 MB of `stadiums_map.json` plus several MB of tournament and insight PNGs, and
  Render clones it anyway.
- **Staleness.** A club redesigns its badge and we keep the old one until
  `download_crests --force`. Today the same lag exists, hidden. Add it to the
  season-update routine.
- **The 36 without crests** are unaffected and still need manual sourcing.
