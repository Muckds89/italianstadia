"""
check_map_integrity
===================
Whole-database checks for the faults that make a map WRONG WITHOUT ERRORING.

Every check here has actually shipped. None of them raised anything, and none was
visible as breakage — a missing coordinate just drops a club, a shared stadium name
just merges two, a stale tier just hides one from a filter. The map looks fine and
is quietly incomplete, which is the worst failure mode this project has.

This is a COMMAND, not a pytest module, on purpose: pytest runs against an empty
test database here, so a data assertion there passes by iterating nothing. Run this
against the real data, after any scrape or season update and before any deploy.

    python -X utf8 manage.py check_map_integrity
    python -X utf8 manage.py check_map_integrity --quiet   # only problems
Exit code 1 if anything is found, so it can gate a deploy.
"""
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand

from italiastadiaapp.models import League, Stadium, Team


class Command(BaseCommand):
    help = "Check the live data for faults that break maps silently."

    def add_arguments(self, p):
        p.add_argument("--quiet", action="store_true", help="print only problems")

    def handle(self, *a, **o):
        problems = 0

        def section(title, rows, explain):
            nonlocal problems
            if rows:
                problems += len(rows)
                self.stdout.write(self.style.ERROR(f"\n{title}: {len(rows)}"))
                self.stdout.write(f"  {explain}")
                for r in rows[:25]:
                    self.stdout.write(f"    {r}")
                if len(rows) > 25:
                    self.stdout.write(f"    ... and {len(rows) - 25} more")
            elif not o["quiet"]:
                self.stdout.write(self.style.SUCCESS(f"{title}: clean"))

        # 1. A ground with no coordinates cannot be plotted, so it is dropped.
        section("Grounds with no coordinates",
                [f"{s.name} <- {', '.join(t.name for t in s.teams.all())}"
                 for s in Stadium.objects.prefetch_related("teams")
                 if (s.latitude is None or s.longitude is None) and s.teams.exists()],
                "these clubs vanish from every map with no error")

        # 2. A club with no ground has nowhere to draw.
        section("Clubs with no ground",
                [f"{t.name} ({t.league.name})" for t in
                 Team.objects.select_related("stadium", "league")
                 .filter(is_national=False, league__hidden=False)
                 .exclude(league__isnull=True) if t.stadium is None],
                "these clubs are missing from their league's map")

        # 3. tier and division_level are separate fields; nothing enforces agreement.
        section("Clubs whose tier disagrees with their league",
                [f"{t.name}: tier={t.tier}, {t.league.name} is level {t.league.division_level}"
                 for t in Team.objects.select_related("league")
                 .filter(is_national=False).exclude(league__isnull=True)
                 if t.tier != t.league.division_level],
                "these drop out of tier-filtered views")

        # 4. A league holding clubs but not declaring a season misreports everywhere.
        section("Leagues with clubs but no season tag",
                [lg.name for lg in League.objects.filter(division_level__gte=1)
                 if lg.teams.exists() and not (lg.season or "").strip()],
                "coverage reports read the season, not the clubs")

        # 5. Shared names are FINE; what matters is that the slugs differ, because
        #    the renderer keys badges and the label-skip set on the slug.
        names = Counter(s.name for s in Stadium.objects.all())
        dup_names = {n for n, c in names.items() if c > 1}
        bad_slugs = []
        for n in sorted(dup_names):
            rows = list(Stadium.objects.filter(name=n))
            if len({s.slug for s in rows}) != len(rows):
                bad_slugs.append(f"{n}: slugs {[s.slug for s in rows]}")
        section("Same-named grounds without distinct slugs", bad_slugs,
                "the renderer keys on the slug; duplicates merge two grounds into one")
        if dup_names and not o["quiet"]:
            self.stdout.write(f"  ({len(dup_names)} stadium name(s) are shared by two or "
                              f"more grounds, which is expected and handled)")

        # 6. Two stadium ROWS at one position is a duplicate record, not a groundshare.
        pos = defaultdict(list)
        for s in Stadium.objects.exclude(latitude=None).exclude(longitude=None):
            pos[(round(float(s.latitude), 4), round(float(s.longitude), 4))].append(s)
        section("Stadium records sharing one coordinate",
                [f"{la},{lo}: " + " | ".join(f"{s.name} ({s.capacity})" for s in v)
                 for (la, lo), v in sorted(pos.items()) if len(v) > 1],
                "either one venue stored twice, or one of them has the wrong position")

        self.stdout.write("")
        if problems:
            self.stdout.write(self.style.ERROR(f"{problems} problem(s) found"))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("no silent-failure problems found"))
