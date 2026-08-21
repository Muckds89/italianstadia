"""
audit_ownership
===============
Re-run the ownership classifier over every stadium and report where the stored
category disagrees with it.

WHY THIS EXISTS. The categories in the database were produced by a keyword matcher
that compared keywords as bare substrings, so " stad" (Dutch for "city") matched the
word "Stadium"/"Stadion" inside a private company's NAME. "The Community Stadium
Limited", "Allianz Arena München Stadion GmbH" and "Brann Stadion AS" were all filed
as municipally owned. "land " (German "Land") matched "Sunderland 100%" the same way.
A Lille supporter spotted the resulting error on a published map.

WHAT IT WILL AND WILL NOT WRITE. --apply writes only POSITIVE corrections: rows where
the classifier is confident and merely disagrees with an older, buggier reading. It
never downgrades a stored category to UNKNOWN, because a stored PRIVATE is often a
human's correct reading of an owner string the matcher cannot parse ("Kroenke Sports
& Entertainment" owns the Emirates). Those rows are listed under REVIEW instead, for a
person to settle.

    python -X utf8 manage.py audit_ownership              # report only
    python -X utf8 manage.py audit_ownership --apply      # write the safe corrections
"""
from collections import Counter

from django.core.management.base import BaseCommand

from italiastadiaapp.models import Stadium
from italiastadiaapp.ownership import classify_ownership

# owner_raw strings carrying one of these were settled by a person against sources.
# The classifier does not get to overrule them; that is the whole point of the note.
CURATED = ("human-verified", "confirmed public", "confirmed private", "verified private")


class Command(BaseCommand):
    help = "Re-check stored stadium ownership against the classifier."

    def add_arguments(self, p):
        p.add_argument("--apply", action="store_true",
                       help="write the positive corrections (never writes UNKNOWN)")
        p.add_argument("--show-review", action="store_true",
                       help="list every row needing human review, not just a count")

    def handle(self, *a, **o):
        positive, review = [], []

        qs = (Stadium.objects.exclude(owner_raw__isnull=True).exclude(owner_raw="")
              .prefetch_related("teams"))
        curated = 0
        for s in qs:
            if any(m in (s.owner_raw or "").lower() for m in CURATED):
                curated += 1
                continue
            clubs = [t.name for t in s.teams.all()]
            new = classify_ownership(s.owner_raw, clubs, s.city.name if s.city_id else None)
            if new == s.ownership:
                continue
            (review if new == "UNKNOWN" else positive).append((s, new, clubs))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nPOSITIVE CORRECTIONS ({len(positive)})"))
        moves = Counter()
        for s, new, _ in positive:
            moves[(s.ownership, new)] += 1
            self.stdout.write(f"  {s.ownership:8} -> {new:8} | {s.name[:34]:34} "
                              f"| {(s.owner_raw or '')[:44]!r}")
        for (old, new), n in moves.most_common():
            self.stdout.write(f"    {old} -> {new}: {n}")

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nNEEDS REVIEW ({len(review)}) — stored category kept, classifier is unsure"))
        if o["show_review"]:
            for s, _, clubs in review:
                self.stdout.write(f"  {s.ownership:8} | {s.name[:34]:34} "
                                  f"| {(s.owner_raw or '')[:40]!r} | {', '.join(clubs[:1])}")
        else:
            self.stdout.write("    (pass --show-review to list them)")

        if o["apply"]:
            for s, new, _ in positive:
                s.ownership = new
                s.save(update_fields=["ownership"])
            self.stdout.write(self.style.SUCCESS(
                f"\napplied {len(positive)} correction(s); {len(review)} left for review"))
        else:
            self.stdout.write(self.style.WARNING(
                f"\nreport only — re-run with --apply to write {len(positive)} correction(s)"))
