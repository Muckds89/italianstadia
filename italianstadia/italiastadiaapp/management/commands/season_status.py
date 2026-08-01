"""
season_status
=============
Show which leagues still carry last season's data, so the 2026/27 refresh can be
done league by league (each league stays live and correctly labelled until its
own scrape runs).

Usage
-----
    python -X utf8 manage.py season_status                  # group by season
    python -X utf8 manage.py season_status --stale 2026/27  # only leagues not yet on 2026/27
"""
from collections import defaultdict

from django.core.management.base import BaseCommand

from italiastadiaapp.models import League, Team


def _slug_for(league):
    """Best-guess urls_<slug>.json name for the scrape command."""
    return league.name.lower().replace(" ", "-").replace(".", "")


class Command(BaseCommand):
    help = "Report the season each league's data reflects."

    def add_arguments(self, parser):
        parser.add_argument(
            "--stale", default="",
            help="Target season (e.g. 2026/27). Lists only leagues NOT yet on it.",
        )

    def handle(self, *args, **opts):
        target = opts["stale"].strip()
        qs = League.objects.select_related("country").order_by(
            "season", "country__name", "division_level")

        counts = defaultdict(int)
        for t in Team.objects.filter(league__isnull=False).values_list("league_id", flat=True):
            counts[t] += 1

        if target:
            qs = qs.exclude(season=target)
            self.stdout.write(self.style.HTTP_INFO(
                f"\nLeagues NOT yet updated to {target}:\n"))
            for lg in qs:
                self.stdout.write(
                    f"  {lg.country.name:<20} {lg.name:<38} "
                    f"{lg.season or '(unset)':<9} {counts.get(lg.id, 0):>3} teams"
                )
            self.stdout.write(f"\n{qs.count()} league(s) to refresh.")
            self.stdout.write(
                "Scrape one with:  python -X utf8 manage.py scrape_season --league <slug>")
            return

        by_season = defaultdict(list)
        for lg in qs:
            by_season[lg.season or "(unset)"].append(lg)
        for season in sorted(by_season):
            leagues = by_season[season]
            self.stdout.write(self.style.HTTP_INFO(
                f"\n{season}  —  {len(leagues)} league(s)"))
            for lg in leagues:
                self.stdout.write(
                    f"  {lg.country.name:<20} {lg.name:<38} {counts.get(lg.id, 0):>3} teams")
        self.stdout.write(f"\nTotal: {qs.count()} leagues.")

        # A league with no teams is almost always a duplicate left behind by a
        # rename (e.g. Divizia Nationala -> Moldovan Super Liga) or a placeholder
        # that was never filled. Surface them so they don't sit unnoticed.
        empty = [lg for lg in qs if counts.get(lg.id, 0) == 0]
        if empty:
            self.stdout.write(self.style.WARNING(
                f"\n{len(empty)} league(s) with NO teams — check for a rename duplicate:"))
            for lg in empty:
                siblings = [o for o in qs
                            if o.country_id == lg.country_id
                            and o.division_level == lg.division_level and o.id != lg.id]
                hint = (" | same-tier: " + ", ".join(
                    f"{o.name} ({counts.get(o.id, 0)} teams)" for o in siblings)) if siblings else ""
                self.stdout.write(f"  {lg.country.name:<20} {lg.name}{hint}")
