# Feature Plan — Data Quality Enforcement for Scraper Pipeline
_Created: 2026-05-27 | Branch: feature/scraper-data-quality_

## Problem / Goal

After each scrape run it is impossible to tell at a glance whether the data landed correctly. Silent failures go undetected: a missing badge URL looks like a successful team record, UNKNOWN ownership passes without warning, and a capacity of 0 is indistinguishable from a missing value. The goal is a post-scrape quality report printed to the console (and logged) that surfaces every data gap immediately, so the operator can fix the source data or JSON before the run is considered done.

---

## Scope

**In scope:**
- [ ] Post-scrape validation summary appended to `run()` — runs automatically after every scrape
- [ ] Standalone management command `python manage.py validate_league_data --league <slug>` for re-checking without re-scraping
- [ ] Checks: UNKNOWN ownership · missing badge (`image_url`) · missing coordinates · missing capacity · zero average attendance

**Out of scope (do not touch):**
- No model changes — validation reads existing fields only
- No scraper logic changes — validation is read-only, post-fact
- No frontend changes
- No blocking/aborting the scrape on failure (warnings only)
- No email / external alerting

---

## Design decisions

1. **Where to add validation**: Append `_validate_league(league)` call at end of `run()` — same process, same log session, zero extra invocation required. | Alternative: separate management command only | Reason: invisible quality gate is better than opt-in; command still added for ad-hoc re-checks.
2. **Output format**: Plain-text table to `logging` (captured in `scraping_transfermarkt.log`) + `print()` to stdout so the operator sees it in the terminal immediately without grepping the log. | Alternative: JSON report file | Reason: log + stdout is already the pattern in this codebase; a file adds friction.
3. **Severity levels**: `WARNING` for fixable gaps (UNKNOWN ownership, missing badge), `ERROR` for blocking gaps (missing lat/lng — marker won't appear on map). | Alternative: single level | Reason: helps triage: errors must be fixed before the data is usable.
4. **Management command location**: `italiastadiaapp/management/commands/validate_league_data.py` | Alternative: standalone script | Reason: consistent with `scrape_season`; gets `python manage.py` discoverability for free.

---

## Checks

| Check | Severity | Field(s) | Condition |
|-------|----------|----------|-----------|
| Missing badge | WARNING | `team.image_url` | None or empty |
| UNKNOWN ownership | WARNING | `stadium.ownership` | `== "UNKNOWN"` |
| Missing capacity | WARNING | `stadium.capacity` | None or 0 |
| Missing coordinates | ERROR | `stadium.latitude`, `stadium.longitude` | Either None |
| Zero avg attendance | WARNING | `team.average_attendance` | None or 0 |

---

## Files that will change

| File | Change type | Why |
|------|-------------|-----|
| `scripts/populate_data_from_transfermrkt.py` | Edit | Add `_validate_league()` function; call it at end of `run()` |
| `italiastadiaapp/management/commands/validate_league_data.py` | New | Standalone management command |

---

## Implementation steps

1. [ ] Write `_validate_league(league)` in `populate_data_from_transfermrkt.py`
   - Query `Team.objects.filter(league=league).select_related("stadium")`
   - For each team run all checks from the table above
   - Print formatted summary: total teams, issue count per check, per-team detail lines for any failures
   - Log same content at `WARNING` / `ERROR` level
2. [ ] Call `_validate_league(league)` at end of `run()`, after the team loop
3. [ ] Create `italiastadiaapp/management/commands/validate_league_data.py`
   - Accepts `--league <slug>` argument
   - Resolves the `League` object via `League.objects.get(...)`
   - Calls `_validate_league(league)`
4. [ ] Run `pytest italiastadiaapp/tests/ -v` — no regressions

---

## Expected console output (example)

```
=== Data Quality Report: Ligue 1 (18 teams) ===
  UNKNOWN ownership  : 0
  Missing badge      : 0
  Missing capacity   : 0
  Missing coordinates: 0
  Zero avg attendance: 2  ← WARNING
    - Paris FC          avg_attendance=0
    - AJ Auxerre        avg_attendance=0

Result: 2 warnings, 0 errors
```

---

## PostgreSQL safety check

N/A — no model changes.

---

## Test plan

- `pytest italiastadiaapp/tests/ -v` — full suite must stay green
- Manual: run `python manage.py scrape_season --league ligue-1 --year 2026` and confirm quality report prints at the end with 0 errors
- Manual: run `python manage.py validate_league_data --league ligue-1` and confirm same report without re-scraping

---

## Rollback plan

Both changes are additive (new function + new command file). To undo: delete `validate_league_data.py` and remove the `_validate_league(league)` call and function from the scraper. No migration to reverse.
