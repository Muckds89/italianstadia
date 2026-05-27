# Feature Plan — Fix Ownership Classifier and Attendance Null Contract
_Created: 2026-05-27 | Branch: fix/ownership-attendance-data-quality_

## Problem / Goal

Two distinct bugs surface together in the data quality report:

**Ownership classifier gaps** — Two Ligue 1 stadiums landed as PRIVATE when they are publicly owned:
- Stade de la Meinau (Strasbourg): Wikipedia owner row contains "Town of Strasbourg" — `"town of"` not in `public_keywords`.
- Stade Océane (Le Havre): Wikipedia owner row contains "agglomeration" / "agglomération" — neither in `public_keywords`.

**Attendance null contract** — `clean_int()` returns `0` when the scraped text parses to `"0"`. The model field is `IntegerField(null=True, blank=True)`, but `0` is not a meaningful attendance figure — it means "no data". The fix makes `clean_int()` return `None` for a parsed value of `0`, establishing the invariant: `None` = no data, any positive integer = real data.

Success = data quality report shows 0 incorrectly classified PRIVATE stadiums for Ligue 1, and `average_attendance` is never stored as `0`.

---

## Scope

**In scope:**
- [x] Add `"town of"`, `"town council"`, `"agglomeration"`, `"agglomération"`, `"communauté"`, `"communaute"` to `public_keywords` in `classify_ownership()`
- [x] Fix `clean_int()` to return `None` when the parsed integer is `0`
- [x] Update `CLAUDE.md` with new keyword entries and `clean_int` null contract

**Out of scope (do not touch):**
- No model migration needed (`average_attendance` is already `null=True`)
- No API or frontend changes
- Validator check update (`_validate_league`) deferred to merge with `feature/scraper-data-quality-checks`

---

## Files changed

| File | Change type | Why |
|------|-------------|-----|
| `scripts/populate_data_from_transfermrkt.py` | Edit | `classify_ownership()` keywords + `clean_int()` null fix |
| `CLAUDE.md` | Edit | Added "Scraper data files" section with keyword list and null contract |

---

## Rollback plan

Pure Python changes, no migration. `git revert` the single commit on this branch.
