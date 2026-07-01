"""Apply manually-filled ownership from scripts/data/ownership_to_fill.csv.

Workflow:
  1. Run scripts that exported ownership_to_fill.csv (already generated).
  2. Open the CSV, fill the `ownership` column with PUBLIC / PRIVATE / MIXED
     for the rows you can verify. Optionally add a short `owner_note`
     (e.g. "Comune di X", "city council") — it is stored in owner_raw.
     Leave the row's ownership blank to skip it.
  3. Run:  python -X utf8 scripts/apply_ownership_csv.py            (apply)
           python -X utf8 scripts/apply_ownership_csv.py --dry-run  (report only)

Filled rows are LOCKED so a future re-scrape will not overwrite them.
"""
import csv
import os
import sys

from italiastadiaapp.models import Stadium

VALID = {"PUBLIC", "PRIVATE", "MIXED"}
CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "ownership_to_fill.csv")


def main():
    dry = "--dry-run" in sys.argv
    applied = skipped = bad = 0
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            val = (row.get("ownership") or "").strip().upper()
            if not val:
                skipped += 1
                continue
            if val not in VALID:
                print(f"  ! bad value {val!r} for id {row.get('id')} ({row.get('name')}) — skipped")
                bad += 1
                continue
            try:
                s = Stadium.objects.get(id=int(row["id"]))
            except (Stadium.DoesNotExist, ValueError, KeyError):
                print(f"  ! no stadium for row {row.get('id')} — skipped")
                bad += 1
                continue
            note = (row.get("owner_note") or "").strip()
            print(f"[{s.id}] {s.name[:34]:<34} {s.ownership:<8} -> {val:<8} {('('+note+')') if note else ''}")
            if not dry:
                s.ownership = val
                if note:
                    s.owner_raw = note
                s.locked = True
                s.save(update_fields=["ownership", "owner_raw", "locked"])
            applied += 1
    print(f"\n{'(dry-run) ' if dry else ''}Applied: {applied} | blank-skipped: {skipped} | bad/missing: {bad}")


if __name__ == "__main__":
    main()
